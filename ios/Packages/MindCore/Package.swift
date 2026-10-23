// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "MindCore",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "MindCore", targets: ["MindCore"])],
    dependencies: [
        .package(url: "https://github.com/swiftlang/swift-markdown.git", exact: "0.9.0"),
    ],
    targets: [
        .target(name: "MindCore", dependencies: [.product(name: "Markdown", package: "swift-markdown")]),
        .testTarget(name: "MindCoreTests", dependencies: ["MindCore"]),
    ]
)
