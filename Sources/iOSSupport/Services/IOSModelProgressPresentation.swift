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
