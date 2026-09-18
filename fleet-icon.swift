import Cocoa

// The app icon, drawn rather than shipped: a dark squircle holding the board
// in miniature -- three lanes, each a status dot and a bar, one running, one
// idle, one quiet. fleet.command compiles and runs this to produce
// AppIcon.icns beside the browser binary, so the repository carries no
// binary and the icon follows the source like everything else here.
//
//   usage: fleet-icon <out.icns>

struct Lane {
    let dot: NSColor
    let glow: Bool
    let bar: CGFloat       // fraction of the available width
}

let lanes = [
    Lane(dot: NSColor(srgbRed: 0.45, green: 0.90, blue: 0.62, alpha: 1), glow: true, bar: 0.96),
    Lane(dot: NSColor(srgbRed: 0.98, green: 0.76, blue: 0.33, alpha: 1), glow: true, bar: 0.62),
    Lane(dot: NSColor(srgbRed: 0.46, green: 0.52, blue: 0.66, alpha: 1), glow: false, bar: 0.80),
]

/// Draw the icon into the current graphics context on a 1024-point canvas.
func draw(scale: CGFloat) {
    guard let ctx = NSGraphicsContext.current?.cgContext else { return }
    ctx.scaleBy(x: scale, y: scale)

    // Apple's template: the shape fills 824 of the 1024 canvas, so the icon
    // sits at the same size as its neighbours in the Dock and Finder.
    let inset: CGFloat = 100
    let shape = NSRect(x: inset, y: inset, width: 1024 - 2 * inset, height: 1024 - 2 * inset)
    let radius: CGFloat = 186

    // Soft drop shadow beneath the plate, as the system's own icons carry.
    ctx.saveGState()
    ctx.setShadow(offset: CGSize(width: 0, height: -14), blur: 34,
                  color: NSColor.black.withAlphaComponent(0.42).cgColor)
    NSColor(srgbRed: 0.07, green: 0.09, blue: 0.15, alpha: 1).setFill()
    NSBezierPath(roundedRect: shape, xRadius: radius, yRadius: radius).fill()
    ctx.restoreGState()

    // The plate: a deep navy, a touch lighter at the top.
    let plate = NSBezierPath(roundedRect: shape, xRadius: radius, yRadius: radius)
    NSGradient(colors: [
        NSColor(srgbRed: 0.13, green: 0.17, blue: 0.27, alpha: 1),
        NSColor(srgbRed: 0.06, green: 0.08, blue: 0.14, alpha: 1),
    ])!.draw(in: plate, angle: -90)

    // A hairline rim catching the light along the top edge.
    ctx.saveGState()
    plate.addClip()
    NSGradient(colors: [
        NSColor.white.withAlphaComponent(0.16),
        NSColor.white.withAlphaComponent(0.0),
    ])!.draw(in: NSRect(x: shape.minX, y: shape.maxY - 220, width: shape.width, height: 220), angle: -90)
    ctx.restoreGState()
    NSColor.white.withAlphaComponent(0.08).setStroke()
    let rim = NSBezierPath(roundedRect: shape.insetBy(dx: 3, dy: 3), xRadius: radius - 3, yRadius: radius - 3)
    rim.lineWidth = 6
    rim.stroke()

    // The lanes. Dots on the left, a bar trailing each one; the two live
    // lanes glow, the quiet one does not.
    let laneHeight: CGFloat = 92
    let gap: CGFloat = 96
    let total = CGFloat(lanes.count) * laneHeight + CGFloat(lanes.count - 1) * gap
    var y = shape.midY + total / 2 - laneHeight
    let left = shape.minX + 176
    let right = shape.maxX - 176
    let dotSize: CGFloat = 92
    let barStart = left + dotSize + 64

    for lane in lanes {
        let dotRect = NSRect(x: left, y: y, width: dotSize, height: dotSize)
        if lane.glow {
            ctx.saveGState()
            ctx.setShadow(offset: .zero, blur: 46, color: lane.dot.withAlphaComponent(0.85).cgColor)
            lane.dot.setFill()
            NSBezierPath(ovalIn: dotRect).fill()
            ctx.restoreGState()
        }
        lane.dot.setFill()
        NSBezierPath(ovalIn: dotRect).fill()
        // A highlight on the dot, so it reads as a lamp rather than a disc.
        NSColor.white.withAlphaComponent(lane.glow ? 0.55 : 0.25).setFill()
        NSBezierPath(ovalIn: NSRect(x: dotRect.minX + 22, y: dotRect.maxY - 40, width: 30, height: 22)).fill()

        let barHeight: CGFloat = 40
        let barRect = NSRect(x: barStart, y: y + (laneHeight - barHeight) / 2,
                             width: (right - barStart) * lane.bar, height: barHeight)
        (lane.glow ? NSColor.white.withAlphaComponent(0.34) : NSColor.white.withAlphaComponent(0.16)).setFill()
        NSBezierPath(roundedRect: barRect, xRadius: barHeight / 2, yRadius: barHeight / 2).fill()

        y -= laneHeight + gap
    }
}

func render(pixels: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                               bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                               colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    rep.size = NSSize(width: pixels, height: pixels)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSGraphicsContext.current?.imageInterpolation = .high
    draw(scale: CGFloat(pixels) / 1024)
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

guard CommandLine.arguments.count > 1 else {
    fputs("usage: fleet-icon <out.icns>\n", stderr)
    exit(2)
}
let out = URL(fileURLWithPath: CommandLine.arguments[1])
let iconset = out.deletingLastPathComponent().appendingPathComponent("AppIcon.iconset")
let fm = FileManager.default
try? fm.removeItem(at: iconset)
try fm.createDirectory(at: iconset, withIntermediateDirectories: true)

// iconutil wants every size at 1x and 2x under these exact names.
for points in [16, 32, 128, 256, 512] {
    try render(pixels: points).write(to: iconset.appendingPathComponent("icon_\(points)x\(points).png"))
    try render(pixels: points * 2).write(to: iconset.appendingPathComponent("icon_\(points)x\(points)@2x.png"))
}

let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = ["-c", "icns", iconset.path, "-o", out.path]
try iconutil.run()
iconutil.waitUntilExit()
try? fm.removeItem(at: iconset)
exit(iconutil.terminationStatus)
