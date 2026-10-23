// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "MindCore",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "MindCore", targets: ["MindCore"])],
    targets: [
        .target(name: "MindCore"),
        .testTarget(name: "MindCoreTests", dependencies: ["MindCore"]),
    ]
)
