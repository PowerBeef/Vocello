import AVFoundation
import Foundation
import QwenVoiceCore

/// Records a 10–20 s reference clip as a 24 kHz mono Int16 PCM WAV for Voice Cloning enrollment,
/// exposing a live amplitude history that drives the level meters on both platforms (iOS
/// `IOSRecordingOverlay`, macOS `MacRecordVoiceSheet`). Does its own permission request;
/// callers don't need to pre-check microphone access.
@MainActor
final class ReferenceClipRecorder: NSObject, ObservableObject {
    static let minDuration: Double = 10.0
    static let maxDuration: Double = 20.0

    @Published private(set) var isRecording: Bool = false
    @Published private(set) var elapsed: Double = 0
    @Published private(set) var amplitude: Double = 0
    /// Rolling history of recent mic levels (oldest → newest, 0…1) that drives the live
    /// level meter so the user can SEE their voice being heard + recorded.
    @Published private(set) var levels: [Double] = []
    @Published var showsPermissionAlert: Bool = false
    @Published private(set) var permissionDenied: Bool = false
    @Published private(set) var lastSavedURL: URL?
    /// True when the in-progress recording was ended by an audio-session
    /// interruption (incoming call, Siri, another app taking the mic) rather
    /// than the user stopping it. The capture up to that point is finalized +
    /// saved (so the take isn't silently lost); the UI surfaces a notice.
    /// Cleared on the next `start()` / `reset()`.
    @Published private(set) var wasInterrupted: Bool = false
    /// True when the last `start()` attempt couldn't begin capturing —
    /// typically no input device (Macs without a microphone) or a hardware
    /// failure. Cleared on the next successful start or `reset()`.
    @Published private(set) var recordingFailed: Bool = false

    /// Whether the system reports any audio-input hardware at all. Always
    /// true on iPhone; on a Mac without a microphone the record UI should
    /// disable capture and explain instead of failing silently.
    static var hasAvailableInputDevice: Bool {
        if virtualMicrophoneURL != nil { return true }
        return AVCaptureDevice.default(for: .audio) != nil
    }

    /// Registered debug-knob virtual microphone for machines without an input
    /// device: when the master runtime gate is enabled and
    /// `QWENVOICE_FAKE_MIC_WAV` points at a readable audio file, `start()`
    /// simulates capture — elapsed time and meter levels come from the clip's
    /// real amplitude envelope — and `stopAndSave()` delivers a copy of the
    /// clip, so the record→review→enroll flow runs end-to-end with no input
    /// hardware and no mic TCC prompt. Inert in production: the knob is
    /// registered in `config/runtime-debug-knobs.json` and ignored unless
    /// `QWENVOICE_DEBUG` enables the master gate.
    static var virtualMicrophoneURL: URL? {
        guard let path = RuntimeDebugGate.value(for: "QWENVOICE_FAKE_MIC_WAV"),
              !path.isEmpty else { return nil }
        let url = URL(fileURLWithPath: path)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    /// ~80 ms/sample × 48 ≈ a 3.8 s scrolling window.
    private let maxLevels = 48

    private var recorder: AVAudioRecorder?
    private var meteringTimer: Timer?
    private var startedAt: Date?
    /// Active virtual-microphone session (see `virtualMicrophoneURL`).
    private var virtualSource: (url: URL, duration: Double, envelope: [Double])?
    #if os(iOS)
    private var interruptionObserver: NSObjectProtocol?
    #endif

    deinit {
        MainActor.assumeIsolated {
            #if os(iOS)
            if let interruptionObserver {
                NotificationCenter.default.removeObserver(interruptionObserver)
            }
            #endif
            meteringTimer?.invalidate()
        }
    }

    /// Re-read the system permission state without prompting — call when the
    /// app becomes active again so a grant made in System Settings clears the
    /// denied UI without a relaunch.
    func refreshPermissionState() {
        guard Self.virtualMicrophoneURL == nil else {
            permissionDenied = false
            return
        }
        switch AVAudioApplication.shared.recordPermission {
        case .granted:
            permissionDenied = false
        case .denied:
            permissionDenied = true
        case .undetermined:
            break
        @unknown default:
            break
        }
    }

    func requestPermissionIfNeeded() async {
        guard Self.virtualMicrophoneURL == nil else { return }
        switch AVAudioApplication.shared.recordPermission {
        case .undetermined:
            _ = await AVAudioApplication.requestRecordPermission()
        case .denied:
            permissionDenied = true
            showsPermissionAlert = true
        case .granted:
            permissionDenied = false
        @unknown default:
            break
        }
    }

    func start() async {
        guard !isRecording else { return }

        if let virtualURL = Self.virtualMicrophoneURL {
            startVirtualCapture(from: virtualURL)
            return
        }

        switch AVAudioApplication.shared.recordPermission {
        case .denied:
            permissionDenied = true
            showsPermissionAlert = true
            return
        case .undetermined:
            let granted = await AVAudioApplication.requestRecordPermission()
            guard granted else {
                permissionDenied = true
                showsPermissionAlert = true
                return
            }
        case .granted:
            break
        @unknown default:
            return
        }

        do {
            #if os(iOS)
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: [])
            try session.setActive(true, options: [])
            #endif

            let url = makeOutputURL()
            // 24 kHz mono Int16 PCM matches the Vocello clone-reference
            // contract; AVAudioRecorder writes a WAV (since the extension
            // is .wav) and the platform handles any required downsampling
            // from the hardware rate.
            let settings: [String: Any] = [
                AVFormatIDKey: Int(kAudioFormatLinearPCM),
                AVSampleRateKey: 24_000,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsBigEndianKey: false,
                AVLinearPCMIsFloatKey: false
            ]
            let recorder = try AVAudioRecorder(url: url, settings: settings)
            recorder.isMeteringEnabled = true
            recorder.delegate = self
            guard recorder.record(forDuration: Self.maxDuration + 0.5) else {
                recordingFailed = true
                return
            }

            self.recorder = recorder
            self.isRecording = true
            self.recordingFailed = false
            self.wasInterrupted = false
            self.startedAt = Date()
            self.elapsed = 0
            self.amplitude = 0
            self.levels = []
            startMetering()
            #if os(iOS)
            registerInterruptionObserver()
            #endif
        } catch {
            isRecording = false
            recordingFailed = true
        }
    }

    #if os(iOS)
    /// Observe audio-session interruptions while recording. An incoming call,
    /// Siri, or another app grabbing the input stops hardware capture; without
    /// this the recorder would sit in a stale `isRecording` state and the take
    /// would be silently dropped. On `.began` we finalize + save whatever was
    /// captured and flag `wasInterrupted` so the UI can explain.
    private func registerInterruptionObserver() {
        guard interruptionObserver == nil else { return }
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] notification in
            // Extract the Sendable raw value before the actor hop — the
            // Notification itself is not Sendable (Swift 6 strict concurrency).
            let typeRaw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            MainActor.assumeIsolated {
                self?.handleAudioSessionInterruption(typeRaw: typeRaw)
            }
        }
    }

    private func removeInterruptionObserver() {
        if let interruptionObserver {
            NotificationCenter.default.removeObserver(interruptionObserver)
            self.interruptionObserver = nil
        }
    }

    private func handleAudioSessionInterruption(typeRaw: UInt?) {
        guard isRecording,
              let typeRaw,
              AVAudioSession.InterruptionType(rawValue: typeRaw) == .began else { return }
        wasInterrupted = true
        _ = stopAndSave()
    }
    #endif

    @discardableResult
    func stopAndSave() -> URL? {
        if let virtualSource {
            meteringTimer?.invalidate()
            meteringTimer = nil
            isRecording = false
            let dest = makeOutputURL()
            do {
                try? FileManager.default.removeItem(at: dest)
                try FileManager.default.copyItem(at: virtualSource.url, to: dest)
                lastSavedURL = dest
                return dest
            } catch {
                recordingFailed = true
                return nil
            }
        }
        guard let recorder else { return nil }
        recorder.stop()
        meteringTimer?.invalidate()
        meteringTimer = nil
        isRecording = false
        #if os(iOS)
        removeInterruptionObserver()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
        lastSavedURL = recorder.url
        return recorder.url
    }

    func stopWithoutSaving() {
        if virtualSource != nil {
            // Mirror the real path: the in-progress/saved file is discarded
            // (callers stash a copy before dismissal, exactly like the
            // hardware flow).
            if let lastSavedURL {
                try? FileManager.default.removeItem(at: lastSavedURL)
            }
            virtualSource = nil
        }
        recorder?.stop()
        if let url = recorder?.url {
            try? FileManager.default.removeItem(at: url)
        }
        recorder = nil
        meteringTimer?.invalidate()
        meteringTimer = nil
        isRecording = false
        elapsed = 0
        amplitude = 0
        levels = []
        #if os(iOS)
        removeInterruptionObserver()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }

    func reset() {
        stopWithoutSaving()
        lastSavedURL = nil
        recordingFailed = false
        wasInterrupted = false
    }

    private func startMetering() {
        meteringTimer?.invalidate()
        meteringTimer = Timer.scheduledTimer(withTimeInterval: 0.08, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.tickMeter()
            }
        }
    }

    /// Begin a simulated capture session driven by the virtual-microphone
    /// clip: same published-state lifecycle as the hardware path, with meter
    /// levels read from the clip's amplitude envelope so the UI stays honest.
    private func startVirtualCapture(from url: URL) {
        guard let file = try? AVAudioFile(forReading: url) else {
            recordingFailed = true
            return
        }
        let sampleRate = max(file.fileFormat.sampleRate, 1)
        let duration = Double(file.length) / sampleRate
        let envelope = Self.amplitudeEnvelope(of: file, windowSeconds: 0.08)
        virtualSource = (url, duration, envelope)
        isRecording = true
        recordingFailed = false
        wasInterrupted = false
        startedAt = Date()
        elapsed = 0
        amplitude = 0
        levels = []
        startMetering()
    }

    /// RMS per `windowSeconds` window across the whole file, mapped to the
    /// same 0…1 visual range the dBFS metering path produces.
    private static func amplitudeEnvelope(of file: AVAudioFile, windowSeconds: Double) -> [Double] {
        let format = file.processingFormat
        let windowFrames = AVAudioFrameCount(max(1, format.sampleRate * windowSeconds))
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: windowFrames) else {
            return []
        }
        var envelope: [Double] = []
        file.framePosition = 0
        while file.framePosition < file.length {
            buffer.frameLength = 0
            guard (try? file.read(into: buffer, frameCount: windowFrames)) != nil,
                  buffer.frameLength > 0,
                  let channel = buffer.floatChannelData?[0] else { break }
            var sum: Double = 0
            for i in 0..<Int(buffer.frameLength) {
                let sample = Double(channel[i])
                sum += sample * sample
            }
            let rms = (sum / Double(buffer.frameLength)).squareRoot()
            // Speech RMS sits around 0.05–0.3; scale + soft gamma so the bars
            // move through most of the meter's range like live input does.
            envelope.append(min(1.0, pow(rms * 4.0, 0.8)))
        }
        return envelope
    }

    private func tickMeter() {
        if let virtualSource {
            guard let startedAt else { return }
            elapsed = Date().timeIntervalSince(startedAt)
            let index = Int(elapsed / 0.08)
            amplitude = index < virtualSource.envelope.count
                ? virtualSource.envelope[index]
                : 0
            levels.append(amplitude)
            if levels.count > maxLevels {
                levels.removeFirst(levels.count - maxLevels)
            }
            if elapsed >= min(virtualSource.duration, Self.maxDuration + 0.4) {
                // Clip exhausted or hardware cap reached; auto-stop and keep it.
                _ = stopAndSave()
            }
            return
        }
        guard let recorder, let startedAt else { return }
        recorder.updateMeters()
        // averagePower is in dBFS (-160 ... 0). Map to 0...1 with light
        // gamma so the meter feels visually responsive without overshooting
        // on loud speech.
        let dB = Double(recorder.averagePower(forChannel: 0))
        let normalized = pow(max(0, (dB + 50) / 50), 1.4)
        amplitude = min(1.0, normalized)
        levels.append(amplitude)
        if levels.count > maxLevels {
            levels.removeFirst(levels.count - maxLevels)
        }
        elapsed = Date().timeIntervalSince(startedAt)
        if elapsed >= Self.maxDuration + 0.4 {
            // Hardware cap reached; auto-stop and keep the WAV.
            _ = stopAndSave()
        }
    }

    private func makeOutputURL() -> URL {
        let tmp = FileManager.default.temporaryDirectory
            .appendingPathComponent("voice-clone-references", isDirectory: true)
        try? FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        let stamp = ISO8601DateFormatter().string(from: Date())
            .replacingOccurrences(of: ":", with: "-")
        return tmp.appendingPathComponent("reference-\(stamp).wav", isDirectory: false)
    }
}

extension ReferenceClipRecorder: AVAudioRecorderDelegate {
    nonisolated func audioRecorderDidFinishRecording(_ recorder: AVAudioRecorder, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.meteringTimer?.invalidate()
            self.meteringTimer = nil
            self.isRecording = false
            if flag {
                self.lastSavedURL = recorder.url
            }
        }
    }
}
