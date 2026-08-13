// swift-tools-version: 6.0
import PackageDescription

// Optional local ASR helper.  It is deliberately a separate Swift package so
// the normal Apple Speech path never links, compiles, or downloads it.
let package = Package(
    name: "AnoTimeParakeetEOU",
    platforms: [.macOS(.v14)],
    dependencies: [
        .package(url: "https://github.com/FluidInference/FluidAudio.git", from: "0.12.4")
    ],
    targets: [
        .executableTarget(
            name: "ParakeetEOUHelper",
            dependencies: [
                .product(name: "FluidAudio", package: "FluidAudio")
            ]
        )
    ]
)
