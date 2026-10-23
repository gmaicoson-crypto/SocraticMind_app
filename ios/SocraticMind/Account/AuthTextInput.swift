import SwiftUI
import UIKit

/// A stable input instance with explicit focus and new-password replacement semantics.
struct AuthTextInput: UIViewRepresentable {
    @Binding var text: String
    let title: String
    let identifier: String
    let secure: Bool
    let contentType: UITextContentType
    let keyboard: UIKeyboardType
    let focus: AuthInputFocus
    let last: Bool
    let onSubmit: () -> Void

    func makeUIView(context: Context) -> UITextField {
        let field = UITextField()
        field.borderStyle = .roundedRect
        field.font = .preferredFont(forTextStyle: .body)
        field.adjustsFontForContentSizeCategory = true
        field.autocapitalizationType = .none
        field.autocorrectionType = .no
        field.placeholder = title
        field.accessibilityLabel = title
        field.accessibilityIdentifier = identifier
        field.text = text
        field.isSecureTextEntry = secure
        field.textContentType = contentType
        field.keyboardType = keyboard
        field.returnKeyType = last ? .done : .next
        field.delegate = context.coordinator
        field.addTarget(context.coordinator, action: #selector(Coordinator.changed), for: .editingChanged)
        focus.register(field, identifier: identifier)
        return field
    }

    func updateUIView(_ field: UITextField, context: Context) {
        context.coordinator.parent = self
        focus.register(field, identifier: identifier)
        let returnKey: UIReturnKeyType = last ? .done : .next
        if field.returnKeyType != returnKey {
            field.returnKeyType = returnKey
        }
        if field.isEnabled != context.environment.isEnabled {
            field.isEnabled = context.environment.isEnabled
        }
        if field.isSecureTextEntry != secure {
            let selection = field.selectedTextRange
            field.isSecureTextEntry = secure
            field.text = text
            field.selectedTextRange = selection
        }
        if field.textContentType != contentType {
            field.textContentType = contentType
        }
        if field.text != text {
            field.text = text
        }
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextField, context _: Context) -> CGSize? {
        CGSize(width: proposal.width ?? uiView.intrinsicContentSize.width,
               height: max(44, uiView.intrinsicContentSize.height))
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    final class Coordinator: NSObject, UITextFieldDelegate {
        var parent: AuthTextInput

        init(_ parent: AuthTextInput) {
            self.parent = parent
        }

        @objc func changed(_ field: UITextField) {
            parent.text = field.text ?? ""
        }

        func textField(_ field: UITextField, shouldChangeCharactersIn range: NSRange,
                       replacementString string: String) -> Bool
        {
            guard parent.contentType == .newPassword, field.markedTextRange == nil else { return true }
            let previous = field.text ?? ""
            guard let replacement = Range(range, in: previous) else { return false }
            // Apply the entire edit once. On iOS 26.5 the default new-password path can
            // turn each typed character into an AutoFill replacement of the whole field.
            let updated = previous.replacingCharacters(in: replacement, with: string)
            field.text = updated
            if let position = field.position(from: field.beginningOfDocument,
                                             offset: range.location + string.utf16.count)
            {
                field.selectedTextRange = field.textRange(from: position, to: position)
            }
            parent.text = updated
            return false
        }

        func textFieldShouldReturn(_: UITextField) -> Bool {
            parent.onSubmit()
            return false
        }
    }
}

/// Weak references avoid owning controls after a form mode is replaced.
@MainActor
final class AuthInputFocus {
    private let fields = NSMapTable<NSString, UITextField>.strongToWeakObjects()

    func register(_ field: UITextField, identifier: String) {
        fields.setObject(field, forKey: identifier as NSString)
    }

    func move(to identifier: String?) {
        if let identifier {
            fields.object(forKey: identifier as NSString)?.becomeFirstResponder()
        } else {
            for field in fields.objectEnumerator()?.allObjects as? [UITextField] ?? [] {
                field.resignFirstResponder()
            }
        }
    }
}
