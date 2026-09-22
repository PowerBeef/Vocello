import AVFoundation
@preconcurrency import XCTest

/// The macOS smoke suite: focused journeys that run in the numbered
/// order (XCTest executes methods alphabetically). Each test owns a fresh
/// app session and leaves no persisted state behind, so a mid-suite failure
/// never poisons the journeys after it and the suite passes back-to-back.
@MainActor
final class VocelloMacSmokeUITests: VocelloMacUITestCase {
    var acceptanceOutputRestore: (original: String?, folders: [URL])?

    override func cleanUpPerTest() {
        if let restore = acceptanceOutputRestore {
            acceptanceOutputRestore = nil
            for folder in restore.folders {
                XCTAssertNoThrow(try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.path))
            }
            restoreOutputFolder(restore.original)
        }
        super.cleanUpPerTest()
    }

    /// The 12 s fixture clears the 10 s minimum duration so the virtual
    /// capture auto-stops into the review stage. It lives in shared `/tmp`
    /// (like the benchmark take-manifest handshake) because the app reading
    /// a file from the test runner's per-app temporary directory triggers the
    /// macOS "access data from other apps" TCC prompt. The lane
    /// (`scripts/ui_test.sh`) synthesizes it — the Xcode 26 test runner
    /// cannot write to `/tmp` itself — and this initializer only writes a
    /// fallback for direct-from-Xcode runs, where the write may or may not
    /// be permitted; `test04` asserts the file exists either way.
    private static let virtualClipURL: URL = {
        let url = URL(fileURLWithPath: "/tmp/vocello-ui-virtual-mic.wav")
        if !FileManager.default.fileExists(atPath: url.path) {
            try? writeSpeechLikeClip(seconds: 12.0, to: url)
        }
        return url
    }()

    // The registered QWENVOICE_FAKE_MIC_WAV input-substitution knob (see
    // config/runtime-debug-knobs.json) is only read by the reference-clip
    // recorder, so carrying it for every journey is inert outside test04.
    override var additionalLaunchEnvironment: [String: String] {
        ["QWENVOICE_FAKE_MIC_WAV": Self.virtualClipURL.path]
    }

    func test00_WindowSizesAndSettingsScene() {
        beginSession()
        defer { endSession() }
        relaunchApp(additionalEnvironment: ["QWENVOICE_UIPERF_SEED_HISTORY": "1"])
        for screen in [VocelloMacScreen.customVoice, .voiceDesign, .voiceCloning] {
            navigate(to: screen)
            replaceScript(with: String(repeating: "The morning light rests on the quiet harbor. ", count: 35))
            assertStudioSizeMatrix("\(screen.rawValue)-long-script")
        }
        app.typeKey(",", modifierFlags: .command)
        let settings = app.windows.containing(.button, identifier: "settings_category_audio").firstMatch
        XCTAssertTrue(VocelloUIWait.exists(settings, timeout: 20), "Cmd+, must open the Settings scene")
        for category in ["audio", "appLanguage", "modelsFiles", "cloning"] {
            XCTAssertTrue(button("settings_category_\(category)", in: settings).isHittable)
        }
        VocelloUIScreenshot.attach(settings, named: "mac-settings-command-comma")
        app.typeKey("w", modifierFlags: .command)
        XCTAssertTrue(VocelloUIWait.condition("Settings window to close", timeout: 10) { !settings.exists })
        XCTAssertTrue(element("screen_voiceCloning").exists, "Closing Settings must preserve Studio")
        assertLibrarySizeMatrix()
    }

    func test10_MissingModelsAndStudioLinks() {
        beginSession()
        defer { endSession() }
        // Existing registered storage isolation, not a model-state override.
        // The app creates an empty profile; installed user/development models
        // remain untouched. No download or deletion action is invoked.
        guard let artifactDirectory = ProcessInfo.processInfo.environment["QVOICE_MAC_BENCH_CAPTURE_DIR"] else {
            XCTFail("Run this journey through scripts/ui_test.sh macos smoke")
            return
        }
        relaunchApp(additionalEnvironment: [
            "QWENVOICE_APP_SUPPORT_DIR": URL(fileURLWithPath: artifactDirectory)
                .appendingPathComponent("empty-model-profile").path,
        ])
        for (screen, mode) in [(VocelloMacScreen.customVoice, "custom"), (.voiceDesign, "design"), (.voiceCloning, "clone")] {
            navigate(to: screen)
            XCTAssertTrue(VocelloUIWait.exists(button("textInput_installModelButton"), timeout: 30))
            assertStudioSizeMatrix("\(mode)-missing-model")
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("textInput_installModelButton"), timeout: 20))
            XCTAssertTrue(VocelloUIWait.exists(element("settings_detail_modelsFiles"), timeout: 20))
            XCTAssertTrue(element("settings_package_pro_\(mode)_speed").exists)
            VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-\(mode)-model-link")
        }
        relaunchApp(additionalEnvironment: additionalLaunchEnvironment)
        assertVisibleSpeedModelReadiness()
    }

    /// Ordinary line-separated batch on the unified sequential streaming
    /// path: two short lines generate as streamed takes with mandatory engine
    /// QC and land in History individually.
    func test07_LineBatchJourney() {
        beginSession()
        defer { endSession() }

        let nonce = "smoke-batch-\(Self.pronounceableNonce())"
        prepare(mode: .custom)

        replaceScript(with: "First batch line.\nSecond batch line.")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("textInput_batchButton"), timeout: 30))
        XCTAssertTrue(button("textInput_batchButton").isSelected)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("textInput_generateButton"), timeout: 30))
        let editor = element("batch_textEditor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 30))
        let lines = "First batch line about the morning tide \(nonce).\nSecond batch line about the evening harbor \(nonce)."
        XCTAssertTrue(VocelloUITextEntry.replace(in: editor, with: lines, timeout: 20))

        let generateAll = button("batch_generateAllButton")
        XCTAssertTrue(VocelloUIWait.exists(generateAll, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generateAll, timeout: 20))

        let done = button("batch_doneButton")
        let statusList = element("batch_itemStatusList")
        XCTAssertTrue(
            VocelloUIWait.progressing(
                "line batch to settle", timeout: 600, stallBudget: 180,
                progress: { statusList.exists ? "\(statusList.label)|\(statusList.value ?? "")" : "no-status-list" }
            ) {
                done.exists && done.isEnabled
            }
        )
        VocelloUIScreenshot.attach(app, named: "mac-smoke-linebatch-complete")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: done, timeout: 20))

        // Both takes must be visible in History exactly once each.
        assertHistoryRows(matching: nonce, expected: 2)
    }

    /// Emits the project wall time (Generate All → settled outcome) for the
    /// lane to combine with the newest v4 manifest — the Xcode 26 test runner
    /// cannot read another app's Application Support (see `virtualClipURL`),
    /// so filesystem work stays lane-side (`scripts/ui_test.sh`). Attached
    /// evidence only; canonical registry publication stays with the benchmark
    /// pipeline and its schema review.
    private func attachLongFormProjectSummary(wallSeconds: TimeInterval) {
        let line = String(format: "LONGFORM_WALL_SECONDS=%.1f", wallSeconds)
        XCTContext.runActivity(named: line) { activity in
            let attachment = XCTAttachment(string: line)
            attachment.name = "long-form-project-wall-seconds"
            attachment.lifetime = .keepAlways
            activity.add(attachment)
        }
        print(line)
    }

    /// Random lowercase pseudo-word: unique enough for History matching while
    /// reading as one spoken token. Hex/UUID nonces are spelled out character
    /// by character with pauses that can trip the punctuation-budget dropout
    /// QC rule on real generations.
    static func pronounceableNonce() -> String {
        let letters = Array("abcdefghijklmnopqrstuvwxyz")
        return String((0..<8).map { _ in letters.randomElement()! })
    }

    func test08_DesignBriefAndCompletedPlayer() {
        beginSession()
        defer { endSession() }

        prepare(mode: .design)
        XCTAssertFalse(element("voiceDesign_voiceDescriptionField").exists,
                       "The brief editor closes so the script owns the Studio canvas")
        replaceScript(with: "The harbor is quiet, and the first light rests on the water.")
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-studio-design-ready")

        // Reopening the genuine chip must retain the brief used for generation.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_voiceBrief"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.value(element("voiceDesign_voiceDescriptionField"),
                                          contains: VocelloUIBenchMatrix.voiceDesignBrief, timeout: 10))
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-studio-design-brief")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voiceBrief_confirm"), timeout: 20))
        generateAndWaitForCompletion(mode: .design, timeout: 300)

        XCTAssertTrue(button("studio_inlinePlayer_playPause").exists)
        XCTAssertFalse(element("sidebarPlayer_bar").exists)
        pinToNarrowestWindow()
        VocelloUILayoutAssert.assertFullyWithinWindow(button("voiceDesign_saveVoiceButton"), of: app)
        VocelloUILayoutAssert.assertFullyWithinWindow(button("studio_inlinePlayer_playPause"), of: app)
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-studio-design-complete")
        assertStudioSizeMatrix("design-complete", completed: true)

        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voiceDesign_saveVoiceButton"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("voicesEnroll_nameField"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.value(element("voicesEnroll_transcriptField"),
                                          contains: "The harbor is quiet", timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("voicesEnroll_cancelButton"), timeout: 20))
        XCTAssertTrue(button("voiceDesign_saveVoiceButton").exists,
                      "Cancelling enrollment must leave the generated take available to save")
    }

    func test09_CloneReferenceAndCompletedPlayer() {
        beginSession()
        defer { endSession() }

        ensureCloneConsentEnabled()
        prepare(mode: .clone)
        replaceScript(with: "The harbor is quiet, and the first light rests on the water.")
        XCTAssertFalse(element("voiceCloning_transcriptInput").exists)
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-studio-clone-ready")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_reference"), timeout: 20))
        let transcript = element("voiceCloning_transcriptInput")
        XCTAssertTrue(VocelloUIWait.exists(transcript, timeout: 20))
        let originalTranscript = transcript.value as? String ?? ""
        XCTAssertFalse(originalTranscript.isEmpty, "Saved reference hydration must retain its transcript")
        XCTAssertTrue(button("voiceCloning_importButton").exists)
        XCTAssertTrue(button("voiceCloning_recordReferenceButton").exists)
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-studio-clone-reference")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("cloneReference_confirm"), timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_reference"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.value(transcript, contains: originalTranscript, timeout: 10))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("cloneReference_confirm"), timeout: 20))

        generateAndWaitForCompletion(mode: .clone, timeout: 300)
        XCTAssertFalse(element("sidebarPlayer_bar").exists)
        pinToNarrowestWindow()
        VocelloUILayoutAssert.assertFullyWithinWindow(button("studio_inlinePlayer_playPause"), of: app)
        VocelloUILayoutAssert.assertFullyWithinWindow(button("studio_inlinePlayer_retry"), of: app)
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-studio-clone-complete")
        assertStudioSizeMatrix("clone-complete", completed: true)
        navigate(to: .history)
        XCTAssertTrue(VocelloUIWait.exists(element("sidebarPlayer_bar"), timeout: 20))
        navigate(to: .voiceCloning)
        XCTAssertTrue(VocelloUIWait.exists(button("studio_inlinePlayer_playPause"), timeout: 20))
        XCTAssertFalse(element("sidebarPlayer_bar").exists)
    }

    func test01_NavigationAndReadiness() {
        // Long-string acceptance uses Foundation's standard pseudo-localization
        // launch arguments. Stable identifiers keep the journey independent of
        // translated labels; no product-only test route is involved.
        beginSession(additionalArguments: ["-ApplePersistenceIgnoreState", "YES"], englishInterface: false)
        defer { endSession() }
        preserveInterfaceLanguage()
        selectInterfaceLanguage("en")
        relaunchApp(additionalEnvironment: [:], additionalArguments: [
            // Isolate window restoration, not persisted language or Studio drafts.
            "-ApplePersistenceIgnoreState", "YES",
            "-NSDoubleLocalizedStrings", "YES",
            "-NSShowNonLocalizedStrings", "YES",
        ])
        for screen in VocelloMacScreen.allCases {
            navigate(to: screen)
        }
        // The four-destination shell returns to the last Studio mode without
        // restoring a different draft or requiring a second navigation click.
        navigate(to: .voiceDesign)
        navigate(to: .voices)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("sidebar_studio"), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_voiceDesign"), timeout: 20))
        XCTAssertTrue(button("sidebar_voiceDesign").isSelected)
        XCTAssertTrue(button("sidebar_studio").isSelected)
        XCTAssertTrue(element("studio_modePicker").exists)

        assertVisibleSpeedModelReadiness()
        ensureCloneConsentEnabled()
        assertSavedCloneVoice()

        // One pin for the whole walk, and it comes after the steps that scroll
        // and click: interaction happens at the size the scene restored to,
        // measurement at the size the app declares as its smallest. Doubled
        // strings at the minimum window is the combination that produces the
        // defects -- a chip row overflowing, a meta row stacking "Clear" into
        // single letters -- and until now nothing ran there.
        pinToNarrowestWindow()

        // Under the doubled strings every row, chip and badge must still be a
        // single legible line with its controls inside the window (the 2026-09-13
        // collapse in Saved Voices was visible only in the screenshot).
        assertSettingsPackageRowsLayoutIntact()
        assertSavedVoicesLayoutIntact()
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-voices-heading-pseudolocalized")
        assertStudioDockFitsAtMinimumWindow()
        VocelloUIScreenshot.attach(app, named: "mac-smoke-readiness-pseudolocalized")

        openSettingsOverview()
        for category in ["audio", "appLanguage", "modelsFiles", "cloning"] {
            VocelloUILayoutAssert.assertFullyWithinWindow(button("settings_category_\(category)"), of: app)
        }
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-settings-overview-pseudolocalized")
        openSettingsCategory("appLanguage")
        VocelloUILayoutAssert.assertFullyWithinWindow(element("settings_appLanguage"), of: app)

        // Check the compact library with ordinary copy as well as doubled strings.
        relaunchApp(additionalEnvironment: [:], additionalArguments: ["-ApplePersistenceIgnoreState", "YES"])
        openSettingsOverview()
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-settings-overview")
        openSettingsCategory("audio")
        VocelloUILayoutAssert.assertFullyWithinWindow(element("preferences_autoPlayToggle"), of: app)
        VocelloUILayoutAssert.assertFullyWithinWindow(element("settings_generationVariation"), of: app)
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-settings-audio")
        assertSavedVoicesLayoutIntact()
        let voiceID = VocelloUIBenchMatrix.cloneVoiceID
        let name = element("voicesRow_\(voiceID)", type: .staticText)
        let use = button("voicesRow_use_\(voiceID)")
        XCTAssertLessThan(abs(name.frame.midY - use.frame.midY), 28,
                          "Primary actions must remain beside the metadata, not below it")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: element("voicesRow_more_\(voiceID)", type: .menuButton), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("voicesRow_delete_\(voiceID)"), timeout: 10))
        app.typeKey(.escape, modifierFlags: [])
        XCTAssertTrue(VocelloUIWait.disappears(element("voicesRow_delete_\(voiceID)"), timeout: 10))
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-voices-compact")

        navigate(to: .history)
        let search = element("history_searchField", type: .searchField)
        XCTAssertTrue(VocelloUITextEntry.replace(in: search, with: "", timeout: 20))
        let heading = app.staticTexts.matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "history_sectionHeading_")
        ).firstMatch
        XCTAssertTrue(VocelloUIWait.exists(heading, timeout: 20))
        VocelloUILayoutAssert.assertFullyWithinWindow(heading, of: app)
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-history-transparent-heading")
        assertAllInterfaceLanguages()
    }

    private func assertAllInterfaceLanguages() {
        let locales = [
            ("zh-Hans", "简体中文", "应用语言"), ("ja", "日本語", "アプリの言語"),
            ("ko", "한국어", "앱 언어"), ("ru", "Русский", "Язык приложения"),
            ("en", "English", "App Language"), ("fr", "Français", "Langue de l’app"),
            ("es", "Español", "Idioma de la app"), ("de", "Deutsch", "App-Sprache"),
            ("it", "Italiano", "Lingua dell’app"), ("pt-BR", "Português (Brasil)", "Idioma do app"),
        ]
        let modes: [VocelloMacScreen] = [.customVoice, .voiceDesign, .voiceCloning]
        var drafts: [String: String] = [:]
        for mode in modes {
            navigate(to: mode)
            drafts[mode.rawValue] = element("textInput_textEditor").value as? String
            XCTAssertNotNil(drafts[mode.rawValue], "Each mode must expose its actual draft")
        }
        for (identifier, nativeName, label) in locales {
            XCTContext.runActivity(named: "Interface language \(identifier): live switch, layout and relaunch") { _ in
                selectInterfaceLanguage(identifier)
                XCTAssertTrue(VocelloUIWait.condition("localized language picker label", timeout: 10) {
                    self.element("settings_appLanguage").label == label
                })
                VocelloUILayoutAssert.assertFullyWithinWindow(element("settings_appLanguage"), of: app)
                VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-locale-\(identifier)-language")
                for category in ["audio", "modelsFiles", "cloning"] {
                    openSettingsCategory(category)
                    VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-locale-\(identifier)-\(category)")
                }
                // Short CJK labels need a glyph-sized floor, not an English word
                // width. Their rendered line height supplies that floor; wrapping
                // and window bounds remain checked, as do the original EN minima.
                assertSettingsPackageRowsLayoutIntact(minimumStatusWidth: nil)
                assertSavedVoicesLayoutIntact(minimumStatusWidth: nil)
                VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-locale-\(identifier)-voices")
                navigate(to: .history)
                VocelloUILayoutAssert.assertFullyWithinWindow(element("history_searchField", type: .searchField), of: app)
                VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-locale-\(identifier)-history")
                for mode in modes {
                    navigate(to: mode)
                    XCTAssertEqual(element("textInput_textEditor").value as? String, drafts[mode.rawValue],
                                   "Switching interface language must preserve \(mode.rawValue) text")
                    XCTAssertFalse(generationAction.label.isEmpty)
                    XCTAssertFalse(generationAction.label.hasPrefix("vocello."))
                    VocelloUILayoutAssert.assertFullyWithinWindow(generationAction, of: app)
                    VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-locale-\(identifier)-\(mode.rawValue)")
                }
                navigate(to: .voiceDesign)
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_voiceBrief"), timeout: 20))
                VocelloUILayoutAssert.assertFullyWithinWindow(button("voiceBrief_confirm"), of: app)
                VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-locale-\(identifier)-brief")
                // An empty brief disables Done. Escape closes this genuine popover
                // without inventing a brief or changing the user's draft.
                app.typeKey(.escape, modifierFlags: [])
                XCTAssertTrue(VocelloUIWait.disappears(element("voiceDesign_voiceSetup"), timeout: 10))
                relaunchApp(additionalEnvironment: [:], additionalArguments: ["-ApplePersistenceIgnoreState", "YES"])
                openSettingsCategory("appLanguage")
                XCTAssertTrue(VocelloUIWait.value(element("settings_appLanguage"), contains: nativeName, timeout: 10))
                XCTAssertEqual(element("settings_appLanguage").label, label)
                for mode in modes {
                    navigate(to: mode)
                    XCTAssertEqual(element("textInput_textEditor").value as? String, drafts[mode.rawValue],
                                   "Relaunch must preserve \(mode.rawValue) text in \(identifier)")
                }
                print("Verified interface language: \(identifier)")
                fflush(stdout)
            }
        }
    }

    func test02_CustomGenerationAndHistory() {
        beginSession()
        defer { endSession() }

        let nonce = "smoke-complete-\(Self.pronounceableNonce())"
        prepare(mode: .custom)
        replaceScript(with: "Automated Built-in Voice smoke generation \(nonce).")
        VocelloUIScreenshot.attach(app, named: "mac-studio-built-in-ready")
        // Played-audio capture (PC-02): the smoke lane taps this one take like a
        // benchmark take; an absent or failing capture never fails the journey.
        let environment = ProcessInfo.processInfo.environment
        let capture = VocelloPlaybackCaptureCoordinator(
            environment: environment,
            runID: environment["QVOICE_MAC_BENCH_RUN_ID"] ?? "macos-xcui-smoke"
        )
        defer { capture?.abort() }
        capture?.beginTake(index: 1, cell: "custom/smoke/warm#0", warmState: "warm")
        generateAndWaitForCompletion(
            mode: .custom, timeout: 240,
            onBeforeGenerate: { capture?.markSubmit() },
            onAfterGenerateClick: { capture?.markSubmitReturned() }
        )
        if let capture, !capture.isIdle {
            let playbackEnded = waitForPlaybackToFinish(timeout: 120)
            _ = VocelloUIWait.condition("captured audio to fall silent after playback", timeout: 5) {
                capture.capturedAudioIsQuiet(forLast: 0.5)
            }
            capture.endTake(playbackEnded: playbackEnded)
        } else {
            capture?.endTake(playbackEnded: false)
        }
        XCTAssertTrue(button("studio_inlinePlayer_playPause").exists)
        XCTAssertFalse(element("sidebarPlayer_bar").exists, "Studio owns the active take's transport")
        VocelloUIScreenshot.attach(app, named: "mac-smoke-custom-complete")

        // The tallest the Studio column ever gets: a finished take turns the
        // dock's CTA into a player card, and that is the state in which the
        // column was measured needing ~603-633 pt against a 560 pt minimum.
        // Generation is over by here, so the pin perturbs no timing.
        pinToNarrowestWindow()
        VocelloUILayoutAssert.assertFullyWithinWindow(
            generationAction, of: app
        )
        VocelloUILayoutAssert.assertFullyWithinWindow(
            button("studio_inlinePlayer_playPause"), of: app
        )
        VocelloUIScreenshot.attach(app, named: "mac-studio-built-in-complete-minimum")
        assertStudioSizeMatrix("built-in-complete", completed: true)

        // The completed take must be visible in History exactly once.
        assertHistoryRows(matching: nonce, expected: 1)
        // And it must be laid out. The nonce is what makes this measurable at
        // all: filtered to one known row, the geometry is bounded and the pass
        // cannot be vacuous, which is not true of History at rest.
        assertHistoryRowsLayoutIntact(filteredTo: nonce)
        XCTAssertTrue(element("sidebarPlayer_bar").exists, "The sidebar carries playback outside Studio")
        VocelloUIScreenshot.attach(app, named: "mac-smoke-history-completed")
        app.typeKey("s", modifierFlags: [.command, .control])
        XCTAssertTrue(VocelloUIWait.condition("sidebar to collapse", timeout: 10) {
            !self.button("sidebar_studio").isHittable
        })
        XCTAssertTrue(button("sidebarPlayer_playPause").isHittable,
                      "Playback must remain available in the detail footer")
        VocelloUILayoutAssert.assertFullyWithinWindow(button("sidebarPlayer_playPause"), of: app)
        VocelloUIScreenshot.attach(app.windows.firstMatch, named: "mac-playback-sidebar-collapsed")
        app.typeKey("s", modifierFlags: [.command, .control])
        XCTAssertTrue(VocelloUIWait.condition("sidebar to expand", timeout: 10) {
            self.button("sidebar_studio").isHittable
        })

        navigate(to: .customVoice)
        XCTAssertTrue(button("studio_inlinePlayer_playPause").exists)
        XCTAssertFalse(element("sidebarPlayer_bar").exists, "Returning to Studio restores one inline transport")

        navigate(to: .voices)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(
            on: button("voicesRow_play_\(VocelloUIBenchMatrix.cloneVoiceID)"), timeout: 20))
        navigate(to: .customVoice)
        XCTAssertEqual(button("studio_inlinePlayer_playPause").label, "Play",
                       "The old result must offer replay rather than pausing the other clip")
        XCTAssertTrue(button("sidebarPlayer_playPause").exists,
                      "The newly selected reference clip keeps its own transport")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studio_inlinePlayer_playPause"), timeout: 20))
        XCTAssertFalse(element("sidebarPlayer_bar").exists,
                       "Replaying the result returns transport ownership to Studio")
    }

    func test03_GenerationCancellation() {
        beginSession()
        defer { endSession() }

        ensureAutoplayEnabled()
        let nonce = "smoke-cancel-\(Self.pronounceableNonce())"
        prepare(mode: .custom)
        replaceScript(
            with: VocelloUIBenchMatrix.text(for: .long)
                + " Beyond the harbor, a narrow road followed the water between fields of clover and weathered stone walls."
                + " A cyclist paused beside the old lighthouse to watch fishing boats return with the changing tide."
                + " In the village square, shopkeepers opened their doors and set baskets of fresh bread on wooden tables."
                + " The quiet morning promised a leisurely journey through familiar streets and unexpected conversations."
                + " Cancellation token \(nonce)."
        )
        startGenerationAndAwaitCancelControl(mode: .custom)
        XCTAssertTrue(VocelloUIWait.exists(button("studio_livePreview_playPause"), timeout: 180))
        navigate(to: .history)
        XCTAssertTrue(VocelloUIWait.exists(element("sidebarPlayer_liveBadge"), timeout: 15))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("sidebarPlayer_dismiss"), timeout: 15))
        navigate(to: .customVoice)
        XCTAssertFalse(button("studio_livePreview_playPause").exists,
                       "A dismissed stream must not retake playback ownership")
        XCTAssertTrue(button("textInput_cancelButton").exists,
                      "Dismissing playback must leave generation under the Cancel control")
        cancelActiveGenerationAndAssertCleanReset()
        VocelloUIScreenshot.attach(app, named: "mac-smoke-cancelled")

        // A user-cancelled take must never land in History.
        assertHistoryRows(matching: nonce, expected: 0)
    }

    func test04_RecordingFlow() {
        XCTAssertTrue(
            FileManager.default.fileExists(atPath: Self.virtualClipURL.path),
            "virtual-microphone fixture WAV must exist before launch"
        )

        beginSession()
        defer { endSession() }

        // Consent lives in Settings; enable it first, then land on Voice Cloning.
        ensureCloneConsentEnabled()
        navigate(to: .voiceCloning)
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: button("studioChip_reference"), timeout: 20))

        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: button("voiceCloning_recordReferenceButton"), timeout: 20),
            "record-reference button must be visible and clickable"
        )
        // Scope sheet queries to the sheet subtree: the level meter animates
        // ~12×/s while recording, and a full-tree query can time out taking
        // accessibility snapshots of the whole window.
        let sheet = app.sheets.firstMatch
        XCTAssertTrue(VocelloUIWait.exists(element("recordClip_record", in: sheet), timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("recordClip_levelMeter", in: sheet), timeout: 10))
        XCTAssertTrue(VocelloUIWait.exists(element("recordClip_timer", in: sheet), timeout: 10))
        VocelloUIScreenshot.attach(app, named: "mac-recording-sheet")

        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: button("recordClip_record", in: sheet), timeout: 10)
        )
        XCTAssertTrue(
            VocelloUIWait.exists(button("recordClip_stop", in: sheet), timeout: 10),
            "stop control must appear once capture is running"
        )

        // The 12 s virtual clip auto-stops at clip end (past the 10 s
        // minimum), landing the sheet in its review stage.
        XCTAssertTrue(
            VocelloUIWait.exists(button("recordClip_use", in: sheet), timeout: 45),
            "review stage must appear after the virtual clip auto-stops"
        )
        XCTAssertTrue(VocelloUIWait.exists(button("recordClip_retake", in: sheet), timeout: 10))
        XCTAssertTrue(
            VocelloUIWait.enabled(button("recordClip_use", in: sheet), timeout: 10),
            "a clip past the 10 s minimum must enable the accept button"
        )
        VocelloUIScreenshot.attach(app, named: "mac-recording-review")

        // Stop before the permission-sensitive scenario: accepting the clip
        // starts transcript auto-fill, which can raise the speech-recognition
        // TCC dialog — a system prompt only a human may answer (see
        // docs/reference/macos-permissions.md). Cancel discards the take and
        // leaves no persisted state behind for later journeys.
        XCTAssertTrue(
            VocelloUIPrimaryAction.perform(on: button("recordClip_cancel", in: sheet), timeout: 10)
        )
        XCTAssertTrue(
            VocelloUIWait.disappears(element("recordClip_use"), timeout: 20),
            "record sheet must dismiss after cancelling"
        )
        VocelloUIScreenshot.attach(app, named: "mac-recording-cancelled")
    }

    func test05_LibrarySurfaces() {
        beginSession()
        defer { endSession() }

        navigate(to: .history)
        XCTAssertTrue(
            VocelloUIWait.exists(element("history_searchField", type: .searchField), timeout: 20)
        )
        XCTAssertTrue(VocelloUIWait.exists(element("history_sortPicker"), timeout: 20))
        openSettingsCategory("modelsFiles")
        XCTAssertTrue(VocelloUIWait.exists(element("settings_modelDownloadsSummary"), timeout: 20))
        openSettingsCategory("appLanguage")
        // beginSession selects English through this genuine control and
        // restores the original interface language at the end of the journey.
        let appLanguage = element("settings_appLanguage")
        XCTAssertTrue(VocelloUIWait.exists(appLanguage, timeout: 20))
        XCTAssertTrue(VocelloUIWait.value(appLanguage, contains: "English", timeout: 10))
        VocelloUIScreenshot.attach(app, named: "mac-smoke-library")
    }

    /// Live long-form v4 acceptance: a >900-character script routes to the
    /// long-form sheet, plans multiple segments, streams them sequentially,
    /// joins the output, and lands in History as a project row with an
    /// expandable segment map. Real generation: expect several minutes.
    func test06_LongFormProjectJourney() {
        beginSession()
        defer { endSession() }

        let nonce = "smoke-longform-\(Self.pronounceableNonce())"
        // Varied natural narration (~1,900 characters -> two planned segments):
        // verbatim sentence repetition can push the model into degenerate
        // delivery, which would test the corpus rather than the pipeline.
        let paragraphs = [
            "Long-form acceptance token \(nonce) opens this narration with a calm, steady voice.",
            "The morning train slipped quietly out of the station, carrying a handful of sleepy travelers toward the coast.",
            "Outside the fogged windows, pale fields gave way to grey water, and the rhythm of the rails settled into a low, hypnotic hum.",
            "By the time the sun finally broke through, most of the passengers had drifted into an unhurried silence.",
            "A conductor moved down the aisle with practiced ease, greeting familiar faces and pausing to answer a question about the tides.",
            "Somewhere behind the last carriage, gulls wheeled over the harbor, their cries thin against the wind.",
            "The narrator lingered on small details: a folded newspaper, a chipped enamel mug, the smell of salt drifting through a cracked window.",
            "Later, the town appeared all at once, stacked in weathered rows above the seawall, chimneys leaning into the light.",
            "People stepped down onto the platform and scattered toward their mornings, and the train breathed out and rested.",
            "The story closed the way it began, with the sea keeping its own patient time beneath a widening sky.",
            "Every ending leaves a little room, the narrator said, for whatever the afternoon decides to become.",
            "And with that, the recording came gently to a close, its final sentence trailing into the sound of distant water.",
            "A second movement began further up the coast, where the road narrowed between dry stone walls and fields of late clover.",
            "Cyclists passed in twos and threes, and an old dog watched them from a doorway without much opinion either way.",
            "In the market square, awnings snapped softly in the breeze while crates of plums and greens changed hands with easy talk.",
            "The clock above the chemist ran four minutes fast, a fact the whole town had agreed to forgive decades ago.",
            "When the rain finally came, it arrived politely, more mist than storm, silvering the slate roofs one street at a time.",
            "Children ran the long way home past the bakery, trading exaggerated stories about the size of the waves beyond the pier.",
            "Evening settled in without ceremony, and the lamps along the seafront warmed to their work one by one.",
            "The narrator let the last image stand on its own: a small boat turning for home, its wake folding back into the dark water.",
        ]
        // QVOICE_MAC_LONGFORM_SEGMENTS (runner env, exported by
        // scripts/ui_test.sh --long-form-segments) scales this same journey to
        // a larger project for explicit local memory-scaling evidence. The
        // default keeps today's two-segment smoke behavior; the extension pool
        // stays distinct prose for the same anti-repetition reason and covers
        // roughly twelve segments.
        let targetSegments = max(
            2,
            Int(ProcessInfo.processInfo.environment["QVOICE_MAC_LONGFORM_SEGMENTS"] ?? "") ?? 2
        )
        var script = paragraphs.joined(separator: " ")
        if targetSegments > 2 {
            var extensionIndex = 0
            while script.count < targetSegments * 950,
                  extensionIndex < Self.longFormExtensionParagraphs.count {
                script += " " + Self.longFormExtensionParagraphs[extensionIndex]
                extensionIndex += 1
            }
            XCTAssertGreaterThan(
                script.count, (targetSegments - 1) * 900,
                "extension corpus is too small to plan \(targetSegments) segments"
            )
        }
        XCTAssertGreaterThan(script.count, 1_300)

        prepare(mode: .custom)
        replaceScript(with: script)

        // Long scripts route the visible Generate action to the long-form sheet.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generationAction, timeout: 30))
        let generateAll = button("batch_generateAllButton")
        XCTAssertTrue(VocelloUIWait.exists(generateAll, timeout: 30))
        let projectStartedAt = Date()
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: generateAll, timeout: 20))

        // Completion: the long-form outcome exposes per-segment regeneration
        // and, on a clean run, no resume affordance. The timeout scales with
        // the planned project size.
        let outcomeTimeout: TimeInterval = targetSegments <= 2
            ? 900
            : TimeInterval(targetSegments) * 300
        let firstRegenerate = button("batch_regenerateSegment_0")
        let resume = button("batch_resumeLongFormButton")
        XCTAssertTrue(
            VocelloUIWait.condition("long-form outcome to settle", timeout: outcomeTimeout) {
                firstRegenerate.exists || resume.exists
            },
            "long-form generation must reach a terminal project outcome"
        )
        XCTAssertTrue(
            firstRegenerate.exists && !resume.exists,
            "a clean long-form run must save every segment (resume affordance means a segment failed)"
        )
        let projectWallSeconds = Date().timeIntervalSince(projectStartedAt)
        attachLongFormProjectSummary(wallSeconds: projectWallSeconds)
        VocelloUIScreenshot.attach(app, named: "mac-smoke-longform-complete")

        let done = button("batch_doneButton")
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: done, timeout: 20))

        // Search renders flat: the nonce appears in the joined row and the
        // first segment row.
        assertHistoryRows(matching: nonce, expected: 2)

        // Cleared search groups the project: the joined row exposes the
        // segment-map toggle.
        let search = element("history_searchField", type: .searchField)
        XCTAssertTrue(VocelloUITextEntry.replace(in: search, with: "", timeout: 20))
        let togglePredicate = NSPredicate(
            format: "identifier BEGINSWITH 'history_longFormSegmentsToggle_'"
        )
        let toggle = app.descendants(matching: .any).matching(togglePredicate).firstMatch
        XCTAssertTrue(
            VocelloUIWait.condition("long-form project row to expose its segment map toggle", timeout: 30) {
                toggle.exists
            }
        )
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: toggle, timeout: 20))
        VocelloUIScreenshot.attach(app, named: "mac-smoke-longform-history-project")

        // Expanded map shows the nonce twice even without search (joined row
        // plus the first segment row).
        assertHistoryRows(matching: nonce, expected: 2)
    }

    /// Distinct continuation prose for scaled long-form runs
    /// (QVOICE_MAC_LONGFORM_SEGMENTS > 2). Kept varied for the same
    /// anti-repetition reason as the base corpus; roughly enough for a
    /// twelve-segment project.
    private static let longFormExtensionParagraphs: [String] = [
        "Further inland, the river widened into a slow brown reach where herons stood like patient punctuation marks.",
        "A ferryman worked the crossing on a chain older than his grandfather, and he trusted it more than any engine.",
        "On the far bank, orchards climbed the hillside in careful terraces, each row holding its own weather.",
        "The narrator paused there to describe the light, which arrived late in the valley and left early, as if on loan.",
        "A schoolhouse bell rang twice for no reason anyone remembered, and the sound carried clear across the water.",
        "Two brothers argued cheerfully about the best way to stack firewood, a debate their family had hosted for decades.",
        "In the churchyard, moss had softened every name, and the yew tree kept its own counsel about all of them.",
        "The road out of the valley turned to gravel, then to habit, then to a pair of ruts remembering a road.",
        "At the summit, wind moved through the grass in long silver strokes, combing the hillside toward evening.",
        "A shepherd's hut leaned into the slope, its tin roof pinned down by stones the size of sleeping cats.",
        "From that height, the sea returned to the story, a pale line stitched along the edge of the world.",
        "The narrator let the silence stretch, because some views ask for fewer words rather than better ones.",
        "Descending, the path crossed a stream five times, and each crossing had its own opinion about wet boots.",
        "A painter had set up her easel by the third crossing, chasing a green she swore existed only on Tuesdays.",
        "They spoke briefly about pigments and patience, and she gave the narrator a plum from her coat pocket.",
        "The plum was sour and perfect, and it earned itself this sentence in the record of the day.",
        "By late afternoon, the trail delivered its walkers to a village that smelled of bread and diesel and rain.",
        "The inn had four rooms, three keys, and one rule, which was that the kitchen closed when the cook said so.",
        "Dinner arrived without a menu: soup, then fish, then a pudding that ended all conversation for a while.",
        "In the snug, an old radio played weather reports for shipping lanes nobody present would ever sail.",
        "A dartboard hung in retirement, its wire long healed over by a decade of quieter evenings.",
        "The narrator wrote three postcards and posted none of them, which is one honest way to keep a diary.",
        "Morning brought a market bus, its driver steering with the confidence of a man who owned both hills.",
        "Passengers boarded with baskets, opinions, and a rooster that had clearly made this trip before.",
        "The bus took corners the way rumors take dinner parties, quickly and with total commitment.",
        "At the terminus, a brass band rehearsed in the square, perfecting a march at a strictly walking pace.",
        "The tuba player nodded at strangers between phrases, conducting hospitality with his eyebrows.",
        "A library occupied the old customs house, its shelves ballasted with atlases of countries since renamed.",
        "The librarian stamped return dates with the gravity of a magistrate and the kindness of a grandmother.",
        "Upstairs, a reading room kept one window open for the swallows, an arrangement both parties respected.",
        "The narrator copied a line from a sailor's memoir: every harbor is a promise the sea only sometimes keeps.",
        "Outside, the afternoon had turned bright and businesslike, drying laundry and settling old puddles.",
        "A locksmith's van idled by the fountain while its owner fed crumbs to pigeons he pretended to dislike.",
        "Children raced paper boats in the gutter stream, cheering for vessels with the lifespans of mayflies.",
        "The story followed the coast road north, where cliffs kept their shoulders squared against the weather.",
        "Lighthouse keepers had left decades ago, but the lamp still turned, faithful as a habit nobody broke.",
        "In a cove below, seals hauled out on warm rocks and regarded the mainland with mild, whiskered skepticism.",
        "A fisherman mended nets with a needle worn to his hand, each knot a small argument won against the sea.",
        "He spoke of winters that sorted neighbors into legends, and summers that apologized for them.",
        "The narrator asked about the oldest boat in the harbor, and received three different true answers.",
        "Toward dusk, the road bent inland through pines, and the air changed its mind about being maritime.",
        "Resin and woodsmoke replaced salt, and the light came down in narrow ladders between the trunks.",
        "A forester's cottage kept bees at its gable end, their traffic ruled by an etiquette older than fences.",
        "Supper was bread and honey and a broth improved by everything the garden could spare that week.",
        "Night arrived early under the trees, and with it the small economies of lamplight and low voices.",
        "The narrator read one chapter aloud to no one, because some rooms deserve to be read to.",
        "Sleep came the way the tide comes, without negotiation and exactly on its own schedule.",
        "The next morning opened with frost on the meadow, brief and bright as a coin flipped into the grass.",
        "A postwoman cycled the forest road with letters for four houses and gossip calibrated for each.",
        "She rang her bell at the blind corner out of respect for a deer that had once disrespected it.",
        "Where the pines thinned, the story found a railway halt with a bench, a clock, and no further ambitions.",
        "The narrator waited there among nettles and timetables, listening for the rail's first faint conversation.",
        "The train that came was two carriages of good intentions, warm and slow and smelling of coffee.",
        "Across the aisle, a chess set travelled in a walnut box, its owner seeking opponents with great optimism.",
        "They played to a draw agreed more out of friendship than position, and shook hands over the border of it.",
        "Stations passed like chapters with excellent titles: Millbrook, Harefield, Saint Osyth of the Ledge.",
        "At each stop, someone's whole day either began or ended, and the train witnessed both without comment.",
        "The narrator noted how landscapes rehearse their transitions, hedgerow to fen, fen to town, town to yard.",
        "By noon, the carriages emptied into a city that wore its river like a favorite scarf, loosely and often.",
        "Bridges repeated themselves upstream in diminishing arches, a stone echo fading into the haze.",
        "A tour guide herded umbrellas past the mint, promising secrets and delivering dates, as guides do.",
        "The narrator chose the quieter bank, where anglers and philosophers practiced their related arts.",
        "A café with six tables served one soup and defended it like a thesis, correctly, as it turned out.",
        "The afternoon spent itself on small change: a gallery, an argument about clouds, a repaired shoelace.",
        "When evening came, the city lit its windows in no particular order, an orchestra tuning rather than playing.",
        "The last ferry crossed with its cargo of tired bicycles and unfinished conversations.",
        "From midstream, both banks looked equally like home, which the narrator recorded as the day's finding.",
        "The story kept one final image for the ledger: streetlamps doubling themselves in the black water.",
        "And there the long account rested, not because the road ended, but because the page did.",
    ]

    /// Writes a mono 24 kHz speech-like PCM WAV: a two-tone "voice" under a
    /// syllable-rate envelope with phrase pauses, so the live level meter
    /// moves through its range the way real speech does.
    private static func writeSpeechLikeClip(seconds: Double, to url: URL) throws {
        let sampleRate = 24_000.0
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatLinearPCM),
            AVSampleRateKey: sampleRate,
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsFloatKey: false,
        ]
        let file = try AVAudioFile(forWriting: url, settings: settings)
        let frames = AVAudioFrameCount(sampleRate * seconds)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames),
              let channel = buffer.floatChannelData?.pointee else {
            throw CocoaError(.fileWriteUnknown)
        }
        buffer.frameLength = frames
        for i in 0..<Int(frames) {
            let t = Double(i) / sampleRate
            let syllable = abs(sin(2.0 * .pi * 2.4 * t))
            let phrase: Double = sin(2.0 * .pi * 0.22 * t) > -0.55 ? 1.0 : 0.0
            let tone = 0.7 * sin(2.0 * .pi * 175.0 * t) + 0.3 * sin(2.0 * .pi * 330.0 * t)
            channel[i] = Float(0.28 * tone * syllable * phrase)
        }
        try file.write(from: buffer)
    }
}
