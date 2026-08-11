// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "RealtimeNotchHelper",
    platforms: [.macOS(.v13)],
    dependencies: [
        .package(url: "https://github.com/MrKai77/DynamicNotchKit.git", exact: "1.1.0")
    ],
    targets: [
        .target(name: "SubtitlePresentation"),
        .executableTarget(
            name: "RealtimeNotchHelper",
            dependencies: ["DynamicNotchKit", "SubtitlePresentation"],
            exclude: ["Resources"]
        )
    ],
    swiftLanguageModes: [.v5]
)
