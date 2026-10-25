import CoreFoundation
import Foundation

/// Foundation's typed integer decoder also accepts 42.0. Keep JSON number types for optional usage.
enum ChatFeedbackJSON {
    private static let contextKey = CodingUserInfoKey(rawValue: "socratic.feedbackNumbers")!

    static func decode<Value: Decodable>(_ type: Value.Type, from data: Data) throws -> Value {
        let decoder = JSONDecoder()
        // An unrepresentable optional number makes usage unknown, never the core response invalid.
        decoder.userInfo[contextKey] = Context(root: try? JSONSerialization.jsonObject(with: data))
        return try decoder.decode(type, from: data)
    }

    static func usage(from decoder: any Decoder) -> ChatJSONValue? {
        guard let context = decoder.userInfo[contextKey] as? Context,
              let object = context.object(at: decoder.codingPath) as? [String: Any],
              let usage = object["usage"] as? [String: Any] else { return nil }
        var fields: [String: ChatJSONValue] = [:]
        for name in ["prompt_tokens", "completion_tokens", "total_tokens"] {
            guard let number = usage[name] as? NSNumber,
                  CFGetTypeID(number) != CFBooleanGetTypeID(),
                  ["c", "C", "s", "S", "i", "I", "l", "L", "q", "Q"].contains(String(cString: number.objCType)),
                  number.decimalValue >= 0, number.decimalValue <= 9_007_199_254_740_991 else { return nil }
            fields[name] = .integer(number.int64Value)
        }
        guard ReportedTokenUsage.decode(.object(fields)) != nil else { return nil }
        return .object(fields)
    }

    private struct Context {
        let root: Any?

        func object(at path: [any CodingKey]) -> Any? {
            var current = root
            for key in path {
                if let index = key.intValue, let array = current as? [Any], array.indices.contains(index) {
                    current = array[index]
                } else if let object = current as? [String: Any] {
                    current = object[key.stringValue]
                } else {
                    return nil
                }
            }
            return current
        }
    }
}

/// Preserve existing metadata fields, but never ask the generic numeric decoder to parse usage.
struct ChatMessageMetadata: Decodable {
    let value: [String: ChatJSONValue]

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: Key.self)
        var fields: [String: ChatJSONValue] = [:]
        for key in container.allKeys where key.stringValue != "usage" {
            if key.stringValue == "error_code" {
                fields[key.stringValue] = (try? container.decode(String.self, forKey: key)).map(ChatJSONValue.string)
            } else {
                fields[key.stringValue] = try container.decode(ChatJSONValue.self, forKey: key)
            }
        }
        if let usage = ChatFeedbackJSON.usage(from: decoder) {
            fields["usage"] = usage
        }
        value = fields
    }

    private struct Key: CodingKey {
        let stringValue: String
        var intValue: Int? {
            nil
        }

        init?(stringValue: String) {
            self.stringValue = stringValue
        }

        init?(intValue _: Int) {
            nil
        }
    }
}
