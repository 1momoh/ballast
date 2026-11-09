// Ballast brand assets · author: 1momoh
// Run from this folder using the command in BRAND.md. No external packages.
import AppKit
import CoreText

let ink = "#101D2B", brass = "#C3A36A", paper = "#F1EBDD"
let red = "#C34E43", muted = "#A8B0B5", rule = "#33414C"
let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
func write(_ name: String, _ content: String) throws {
    try content.write(to: root.appendingPathComponent(name), atomically: true, encoding: .utf8)
}
func n(_ value: CGFloat) -> String { String(format: "%.3f", Double(value)) }
func svg(_ w: Int, _ h: Int, _ title: String, _ body: String) -> String {
    """
    <svg xmlns="http://www.w3.org/2000/svg" width="\(w)" height="\(h)" viewBox="0 0 \(w) \(h)" role="img" aria-labelledby="title desc">
      <title id="title">\(title)</title>
      <desc id="desc">Ballast: a rising Plimsoll waterline and a released ballast weight. Author: 1momoh.</desc>
      <metadata>Author: 1momoh. Ballast brand system.</metadata>
    \(body)
    </svg>
    """
}
// 128-unit master; all construction coordinates and stroke widths use an 8-unit grid.
func mark(_ color: String) -> String {
    """
    <g fill="none" stroke="\(color)" stroke-width="8" stroke-linecap="butt" stroke-linejoin="miter">
      <circle cx="64" cy="56" r="32"/>
      <path d="M16 56H96V40H112"/>
    </g>
    <path d="M48 96H80L72 112H56Z" fill="\(color)"/>
    """
}
// CoreText supplies kerning; the resulting files contain outlines, not font references.
func text(_ value: String, x: CGFloat, y: CGFloat, size: CGFloat,
          color: String, fontName: String = "Futura-Medium") -> String {
    let font = CTFontCreateWithName(fontName as CFString, size, nil)
    let attributed = NSAttributedString(string: value, attributes: [
        NSAttributedString.Key(kCTFontAttributeName as String): font
    ])
    let line = CTLineCreateWithAttributedString(attributed)
    var paths = ""
    for run in CTLineGetGlyphRuns(line) as! [CTRun] {
        let count = CTRunGetGlyphCount(run)
        var glyphs = [CGGlyph](repeating: 0, count: count)
        var positions = [CGPoint](repeating: .zero, count: count)
        CTRunGetGlyphs(run, CFRange(location: 0, length: 0), &glyphs)
        CTRunGetPositions(run, CFRange(location: 0, length: 0), &positions)
        let runFont = (CTRunGetAttributes(run) as NSDictionary)[kCTFontAttributeName] as! CTFont
        for i in 0..<count {
            guard let path = CTFontCreatePathForGlyph(runFont, glyphs[i], nil) else { continue }
            let offset = positions[i]
            var d = ""
            path.applyWithBlock { ptr in
                let e = ptr.pointee
                func p(_ index: Int) -> String {
                    let point = e.points[index]
                    return "\(n(point.x + offset.x)) \(n(point.y + offset.y))"
                }
                switch e.type {
                case .moveToPoint: d += "M\(p(0))"
                case .addLineToPoint: d += "L\(p(0))"
                case .addQuadCurveToPoint: d += "Q\(p(0)) \(p(1))"
                case .addCurveToPoint: d += "C\(p(0)) \(p(1)) \(p(2))"
                case .closeSubpath: d += "Z"
                @unknown default: fatalError("Unknown path element")
                }
            }
            paths += "<path d=\"\(d)\"/>\n"
        }
    }
    return "<g aria-label=\"\(value)\" fill=\"\(color)\" transform=\"translate(\(n(x)) \(n(y))) scale(1 -1)\">\n\(paths)</g>"
}
func banner(_ w: Int, _ h: Int) -> String {
    // A separate composition keeps the X header in proportion rather than stretching it.
    let dy: CGFloat = h == 500 ? 50 : 0
    let right = w - 64
    var body = "<rect width=\"\(w)\" height=\"\(h)\" fill=\"\(ink)\"/>"
    body += "<g transform=\"translate(64 \(n(72+dy))) scale(2)\">\(mark(brass))</g>"
    body += text("DEVELOPER / AI CACHE RELEASE", x: 376, y: 65+dy, size: 13, color: brass, fontName: "Menlo-Regular")
    body += text("Ballast", x: 370, y: 172+dy, size: 112, color: paper)
    body += text("Drop the weight you won't miss.", x: 376, y: 239+dy, size: 30, color: paper)
    body += text("a Hermes Agent plugin", x: 376, y: 326+dy, size: 16, color: muted, fontName: "Menlo-Regular")
    // A restrained instrument scale echoes the Desktop free-space gauge.
    body += "<g transform=\"translate(\(right-152) \(n(88+dy)))\" fill=\"none\" stroke=\"\(rule)\" stroke-width=\"1\"><path d=\"M0 0V224M-32 112H152\"/>"
    for i in 0...7 {
        body += "<path d=\"M0 \(i*32)H\(i % 2 == 0 ? 32 : 16)\"/>"
    }
    body += "<path d=\"M-32 144H80V80H152\" stroke=\"\(brass)\" stroke-width=\"2\"/><path d=\"M136 0H152\" stroke=\"\(red)\" stroke-width=\"3\"/></g>"
    body += text("01 / FREE SPACE", x: CGFloat(right-152), y: 350+dy, size: 11, color: muted, fontName: "Menlo-Regular")
    return svg(w, h, "Ballast — Drop the weight you won't miss.", body)
}

func bitmap(_ width: Int, _ height: Int) -> NSBitmapImageRep {
    NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: width, pixelsHigh: height,
      bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
      colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
}
func render(_ source: String, _ output: String, _ width: Int, _ height: Int) throws {
    guard let image = NSImage(contentsOf: root.appendingPathComponent(source)) else {
        fatalError("Native SVG renderer could not load \(source)")
    }
    let rep = bitmap(width, height)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSGraphicsContext.current!.imageInterpolation = .high
    image.draw(in: NSRect(x: 0, y: 0, width: width, height: height))
    NSGraphicsContext.restoreGraphicsState()
    try rep.representation(using: .png, properties: [:])!.write(to: root.appendingPathComponent(output))
    let loaded = NSBitmapImageRep(data: try Data(contentsOf: root.appendingPathComponent(output)))!
    precondition(loaded.pixelsWide == width && loaded.pixelsHigh == height)
    let reference = loaded.colorAt(x: 0, y: 0)!
    var different = 0
    for y in stride(from: 0, to: height, by: max(1, height/100)) {
        for x in stride(from: 0, to: width, by: max(1, width/100)) {
            if loaded.colorAt(x: x, y: y)! != reference { different += 1 }
        }
    }
    precondition(different > 10, "Blank image: \(output)")
    print("Verified \(output): \(width)×\(height), \(different) non-background samples")
}

try write("ballast-icon.svg", svg(128, 128, "Ballast", "<rect width=\"128\" height=\"128\" fill=\"\(ink)\"/>\n" + mark(brass)))
try write("ballast-icon-mono.svg", svg(128, 128, "Ballast — single colour", mark("currentColor")))
try write("ballast-wordmark.svg", svg(1000, 256, "Ballast", "<g transform=\"translate(16 0) scale(2)\">\(mark(brass))</g>\n" + text("Ballast", x: 296, y: 189, size: 160, color: ink)))
try write("ballast-banner.svg", banner(1600, 400))
try write("ballast-banner-1500x500.svg", banner(1500, 500))
for size in [1024, 512, 64] {
    try render("ballast-icon.svg", "ballast-icon-\(size).png", size, size)
}
try render("ballast-wordmark.svg", "ballast-wordmark-2000w.png", 2000, 512)
try render("ballast-banner.svg", "ballast-banner-1600x400.png", 1600, 400)
try render("ballast-banner-1500x500.svg", "ballast-banner-1500x500.png", 1500, 500)
try FileManager.default.createDirectory(at: root.appendingPathComponent(".build"), withIntermediateDirectories: true)
try render("ballast-icon.svg", ".build/ballast-icon-16.png", 16, 16)
// Contact sheet includes actual-size and enlarged small icons for visual inspection.
let sheet = bitmap(1600, 1080)
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: sheet)
NSColor(calibratedWhite: 0.97, alpha: 1).setFill()
NSRect(x: 0, y: 0, width: 1600, height: 1080).fill()
for (name, rect) in [
    ("ballast-banner-1600x400.png", NSRect(x:0,y:680,width:1600,height:400)),
    ("ballast-banner-1500x500.png", NSRect(x:600,y:345,width:900,height:300)),
    ("ballast-wordmark-2000w.png", NSRect(x:600,y:90,width:900,height:230.4)),
    ("ballast-icon-512.png", NSRect(x:24,y:120,width:512,height:512)),
    ("ballast-icon-64.png", NSRect(x:24,y:24,width:64,height:64)),
    (".build/ballast-icon-16.png", NSRect(x:112,y:24,width:16,height:16)),
    (".build/ballast-icon-16.png", NSRect(x:152,y:24,width:64,height:64))
] {
    NSGraphicsContext.current!.imageInterpolation = name.contains("16.png") ? .none : .high
    NSImage(contentsOf: root.appendingPathComponent(name))!.draw(in: rect)
}
NSGraphicsContext.restoreGraphicsState()
try sheet.representation(using:.png, properties:[:])!.write(to:root.appendingPathComponent(".build/inspection.png"))
