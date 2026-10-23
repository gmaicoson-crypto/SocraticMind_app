import Foundation

/// A single-stream parser. JSON semantics and request recovery belong to separate owners.
public struct SSEDecoder {
    public enum Failure: Error, Equatable {
        case invalidLimit, closed, invalidUTF8, lineTooLarge, eventTooLarge
    }

    private let maxLineBytes: Int
    private let maxEventBytes: Int
    private var line: [UInt8] = []
    private var data: [String] = []
    private var eventBytes = 0
    private var skipLineFeed = false
    private var firstLine = true
    private var closed = false

    public init(maxLineBytes: Int = 64 * 1024, maxEventBytes: Int = 256 * 1024) throws {
        guard maxLineBytes > 0, maxEventBytes > 0 else { throw Failure.invalidLimit }
        self.maxLineBytes = maxLineBytes
        self.maxEventBytes = maxEventBytes
    }

    public mutating func feed(_ bytes: some Sequence<UInt8>) throws -> [String] {
        guard !closed else { throw Failure.closed }
        var events: [String] = []
        do {
            for byte in bytes {
                if skipLineFeed, byte == 10 {
                    skipLineFeed = false
                    continue
                }
                skipLineFeed = false
                if byte == 10 || byte == 13 {
                    try consumeLine(into: &events)
                    skipLineFeed = byte == 13
                } else {
                    guard line.count < maxLineBytes else { throw Failure.lineTooLarge }
                    line.append(byte)
                }
            }
        } catch {
            finish()
            throw error
        }
        return events
    }

    /// EOF discards an unseparated event. It is not proof of a successful chat request.
    public mutating func finish() {
        closed = true
        line.removeAll()
        data.removeAll()
        eventBytes = 0
    }

    private mutating func consumeLine(into events: inout [String]) throws {
        let size = line.count
        guard var text = String(bytes: line, encoding: .utf8) else { throw Failure.invalidUTF8 }
        line.removeAll(keepingCapacity: true)
        if firstLine {
            if text.hasPrefix("\u{FEFF}") {
                text.removeFirst()
            }
            firstLine = false
        }
        if text.isEmpty {
            if !data.isEmpty {
                events.append(data.joined(separator: "\n"))
            }
            data.removeAll(keepingCapacity: true)
            eventBytes = 0
            return
        }
        guard size <= maxEventBytes - eventBytes else { throw Failure.eventTooLarge }
        eventBytes += size
        let parts = text.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        if parts[0] == "data" {
            var value = parts.count == 1 ? "" : String(parts[1])
            if value.hasPrefix(" ") {
                value.removeFirst()
            }
            data.append(value)
        }
    }
}
