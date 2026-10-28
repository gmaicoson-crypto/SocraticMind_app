import CoreFoundation
import Foundation

/// Foundation's generic Int decoding accepts 1.0; state versions require JSON integers.
enum JSONScalar {
    static func integer(_ value: Any?, in range: ClosedRange<Int64>) -> Int64? {
        guard let number = value as? NSNumber,
              CFGetTypeID(number) != CFBooleanGetTypeID(),
              ["c", "C", "s", "S", "i", "I", "l", "L", "q", "Q"].contains(String(cString: number.objCType)),
              number.decimalValue >= Decimal(range.lowerBound),
              number.decimalValue <= Decimal(range.upperBound) else { return nil }
        return number.int64Value
    }
}
