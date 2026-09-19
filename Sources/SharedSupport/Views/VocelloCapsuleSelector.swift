import SwiftUI

/// Shared 3-way capsule selector used by `IOSGenerationModeSelector`
/// (Studio mode) and previously by Library / History filter rows.
///
/// R3 (2026-05-21): matches `design_references/Vocello iOS/app.css`
/// `.vc-mode-segmented` plus `chrome.jsx`'s active-mode inline style:
///
///   rail:  rgba(255,255,255,0.04) fill + 0.5pt rgba(255,255,255,0.08)
///          stroke. Neutral, not mode-tinted.
///   pill:  active tint @ 22 % fill + active tint @ 36 % stroke,
///          white inset top highlight, and 1pt black drop shadow.
struct VocelloCapsuleSelector<Item: Identifiable & Hashable>: View {
    let items: [Item]
    @Binding var selection: Item
    let title: KeyPath<Item, String>
    let selectedTint: (Item) -> Color
    var isSelectionDisabled = false
    let controlAccessibilityIdentifier: String
    let itemAccessibilityIdentifier: (Item) -> String
    var stacksVertically = false
    var fillsSegmentWidth = false
    var labelFont: Font = .subheadline.weight(.semibold)
    var reduceMotion = false
    @Namespace private var selectionPillNamespace

    var body: some View {
        let layout = stacksVertically
            ? AnyLayout(VStackLayout(spacing: 2))
            : AnyLayout(HStackLayout(spacing: 4))

        layout {
            ForEach(items) { item in
                Button {
                    guard !isSelectionDisabled else { return }
                    guard item != selection else { return }
                    selection = item
                } label: {
                    Text(item[keyPath: title])
                        .font(labelFont)
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                        .foregroundStyle(
                            item == selection
                                ? VocelloTheme.Text.primary
                                : VocelloTheme.Text.secondary
                        )
                        .frame(minHeight: 36)
                        .padding(.horizontal, stacksVertically ? 6 : 20)
                        .frame(maxWidth: fillsSegmentWidth ? .infinity : nil)
                        .background {
                            if item == selection {
                                VocelloCapsuleSelectorPill(tint: selectedTint(item))
                                    .matchedGeometryEffect(id: "selectionPill", in: selectionPillNamespace)
                            }
                        }
                }
                .buttonStyle(.plain)
                // Keep the 36-point visual pill inside the compact 44-point rail while making
                // the semantic segment itself own the full HIG activation height.
                .frame(maxWidth: .infinity, minHeight: 44)
                .contentShape(Rectangle())
                .disabled(isSelectionDisabled && item != selection)
                .opacity(isSelectionDisabled && item != selection ? 0.42 : 1)
                .animation(reduceMotion ? nil : VocelloTheme.Motion.selectorLabel, value: selection)
                .accessibilityIdentifier(itemAccessibilityIdentifier(item))
                .accessibilityAddTraits(item == selection ? .isSelected : [])
            }
        }
        .animation(reduceMotion ? nil : VocelloTheme.Motion.modePillSlide, value: selection)
        .padding(.horizontal, 4)
        .frame(maxWidth: .infinity)
        .background {
            Capsule(style: .continuous)
                .fill(Color.white.opacity(0.04))
        }
        .overlay {
            Capsule(style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 0.5)
        }
        .frame(height: stacksVertically ? 136 : 44)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier(controlAccessibilityIdentifier)
    }
}

/// The moving capsule pill behind the selected segment.
/// Tinted per `chrome.jsx`'s `color-mix(in oklch, activeColor 22%)`
/// override on `.vc-mode-pill`.
private struct VocelloCapsuleSelectorPill: View {
    let tint: Color

    var body: some View {
        let shape = Capsule(style: .continuous)
        shape
            .fill(tint.opacity(0.22))
            .overlay {
                shape.stroke(tint.opacity(0.36), lineWidth: 0.5)
            }
            .overlay(alignment: .top) {
                // inset 0 1px 0 rgba(255,255,255,0.10) — top-edge highlight
                shape
                    .stroke(Color.white.opacity(0.10), lineWidth: 0.5)
                    .mask(
                        LinearGradient(
                            colors: [.white, .clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    )
            }
            .shadow(color: .black.opacity(0.15), radius: 1, x: 0, y: 1)
    }
}
