import Foundation

/// One bounded file and small UTF-8 fields, encoded without exposing filenames as header syntax.
public struct MultipartUpload: Sendable {
    let body: Data
    let contentType: String

    public init(fields: [String: String], fileField: String, filename: String, mimeType: String, data: Data) throws {
        func valid(_ text: String, allowed: String, maximum: Int) -> Bool {
            !text.isEmpty && text.utf8.count <= maximum && text.utf8.allSatisfy { allowed.utf8.contains($0) }
        }
        let nameCharacters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        let mimeParts = mimeType.split(separator: "/", omittingEmptySubsequences: false)
        guard fields.count <= 16, fields.keys.allSatisfy({ valid($0, allowed: nameCharacters, maximum: 64) }),
              fields.values.reduce(0, { $0 + $1.utf8.count }) <= 16384,
              valid(fileField, allowed: nameCharacters, maximum: 64), fields[fileField] == nil,
              valid(filename, allowed: nameCharacters + ".", maximum: 100), mimeParts.count == 2,
              mimeType.utf8.count <= 100,
              mimeParts
                  .allSatisfy({ valid(String($0), allowed: "abcdefghijklmnopqrstuvwxyz0123456789.+_-", maximum: 98) }),
              !data.isEmpty, data.count <= 5 * 1024 * 1024 else { throw TransportFailure.invalidRequest }
        var boundary: String
        repeat {
            boundary = "SocraticMind-" + UUID().uuidString
        } while data.range(of: Data(boundary.utf8)) != nil || fields.values.contains(where: { $0.contains(boundary) })
        var output = Data()
        func append(_ value: String) {
            output.append(contentsOf: value.utf8)
        }
        for (name, value) in fields.sorted(by: { $0.key < $1.key }) {
            append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n")
        }
        append("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(fileField)\"; filename=\"\(filename)\"\r\n")
        append("Content-Type: \(mimeType)\r\n\r\n")
        output.append(data); append("\r\n--\(boundary)--\r\n")
        body = output; contentType = "multipart/form-data; boundary=\(boundary)"
    }
}
