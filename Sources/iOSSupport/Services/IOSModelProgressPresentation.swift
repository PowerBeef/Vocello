import Foundation

/// Pure presentation contract for model delivery. File transfer is the only lifecycle phase with
/// an honest denominator; verification and publication deliberately remain indeterminate.
struct IOSModelProgressPresentation: Equatable, Sendable {
    enum Indicator: Equatable, Sendable {
        case determinate(fraction: Double, accessibilityValue: String)
        case indeterminate
    }

    let indicator: Indicator
    let detail: String

    static func transfer(
        durableBytes: Int64,
        catalogBytes: Int64?,
        bytesPerSecond: Int64? = nil,
        estimatedSecondsRemaining: Double? = nil,
        suffix: String? = nil,
        formatBytes: (Int64) -> String
    ) -> Self {
        let durableBytes = max(durableBytes, 0)
        guard let catalogBytes, catalogBytes > 0 else {
            var details = ["\(formatBytes(durableBytes)) downloaded"]
            appendOptionalTransferDetails(
                to: &details,
                bytesPerSecond: bytesPerSecond,
                estimatedSecondsRemaining: estimatedSecondsRemaining,
                suffix: suffix,
                formatBytes: formatBytes
            )
            return Self(indicator: .indeterminate, detail: details.joined(separator: " · "))
        }

        let visibleBytes = min(durableBytes, catalogBytes)
        if visibleBytes >= catalogBytes {
            return Self(
                indicator: .indeterminate,
                detail: "Download complete — finishing setup."
            )
        }

        let fraction = min(max(Double(visibleBytes) / Double(catalogBytes), 0), 1)
        let percent = Int((fraction * 100).rounded(.down))
        var details = [
            "\(percent)% · \(formatBytes(visibleBytes)) of \(formatBytes(catalogBytes))"
        ]
        appendOptionalTransferDetails(
            to: &details,
            bytesPerSecond: bytesPerSecond,
            estimatedSecondsRemaining: estimatedSecondsRemaining,
            suffix: suffix,
            formatBytes: formatBytes
        )
        return Self(
            indicator: .determinate(
                fraction: fraction,
                accessibilityValue: "\(percent)% — \(visibleBytes) of \(catalogBytes) bytes"
            ),
            detail: details.joined(separator: " · ")
        )
    }

    static let verification = Self(
        indicator: .indeterminate,
        detail: "Checking downloaded files."
    )

    static let installation = Self(
        indicator: .indeterminate,
        detail: "Making the model available offline."
    )

    static func retrying(retryCount: Int, reason: String?) -> Self {
        var detail = "Preparing retry \(max(1, retryCount))"
        if let reason, !reason.isEmpty {
            detail += ": \(reason)"
        }
        detail += ". Verified files will be reused."
        return Self(indicator: .indeterminate, detail: detail)
    }

    /// Keeps an incomplete determinate rail visibly incomplete after pixel quantization while
    /// preserving the exact byte fraction in the presentation and accessibility contract.
    /// A segment no thicker than the rail itself is reserved at either end, so the rendered
    /// geometry remains within two percentage points on the 300-point model-management rail.
    static func visibleDeterminateFillWidth(
        fraction: Double,
        width: Double,
        thickness: Double
    ) -> Double {
        guard width.isFinite, width > 0 else { return 0 }
        let clamped = min(max(fraction.isFinite ? fraction : 0, 0), 1)
        guard clamped > 0 else { return 0 }
        guard clamped < 1 else { return width }
        let minimumSegment = min(max(thickness, 0), width / 2)
        return min(
            max(width * clamped, minimumSegment),
            width - minimumSegment
        )
    }

    private static func appendOptionalTransferDetails(
        to details: inout [String],
        bytesPerSecond: Int64?,
        estimatedSecondsRemaining: Double?,
        suffix: String?,
        formatBytes: (Int64) -> String
    ) {
        if let bytesPerSecond, bytesPerSecond > 0 {
            details.append("\(formatBytes(bytesPerSecond))/s")
        }
        if let estimatedSecondsRemaining,
           estimatedSecondsRemaining.isFinite,
           estimatedSecondsRemaining > 0 {
            details.append("about \(max(1, Int(estimatedSecondsRemaining.rounded())))s remaining")
        }
        if let suffix, !suffix.isEmpty {
            details.append(suffix)
        }
    }
}
