import Foundation

public enum MarkdownLink {
    /// Browser links only; never resolve message-provided relative paths against the authenticated backend.
    public static func safe(_ value: String) -> String? {
        guard value.range(of: "%(?:0[0-9a-f]|1[0-9a-f]|7f)", options: [.regularExpression, .caseInsensitive]) == nil,
              value.range(of: "%(?![0-9a-fA-F]{2})", options: .regularExpression) == nil,
              !value.unicodeScalars.contains(where: {
                  CharacterSet.whitespacesAndNewlines.contains($0) || CharacterSet.controlCharacters
                      .contains($0) || $0 == "\\"
              }), value.lowercased().hasPrefix("https://") || value.lowercased().hasPrefix("http://"),
              var components = URLComponents(string: value), let host = components.host, !host.isEmpty,
              components.user?.isEmpty != false, components.password?.isEmpty != false
        else { return nil }
        let scheme = components.scheme?.lowercased()
        if let port = components.port, !(1 ... 65535).contains(port) {
            return nil
        }
        components.scheme = scheme
        components.host = host.lowercased()
        components.user = nil; components.password = nil
        if components.path.isEmpty {
            components.path = "/"
        }
        if (scheme == "https" && components.port == 443) || (scheme == "http" && components.port == 80) {
            components.port = nil
        }
        return components.url?.absoluteString
    }
}
