// make_collage.swift — composite the unidentified Vancouver photos into one labeled PNG for Slack.
import Foundation
import CoreGraphics
import ImageIO
import CoreText
import UniformTypeIdentifiers

struct Cell { let path: String; let label: String; let group: String }
let cells: [Cell] = [
  Cell(path:"photos/IMG_6133.jpeg", label:"IMG_6133 · 18:54", group:"CAFE ?"),
  Cell(path:"photos/IMG_6135.jpeg", label:"IMG_6135 · 18:54", group:"CAFE ?"),
  Cell(path:"photos/IMG_6136.jpeg", label:"IMG_6136 · 19:01", group:"CAFE ?"),
  Cell(path:"photos/IMG_6140.jpeg", label:"IMG_6140 · 19:31", group:"JAPANESE ?"),
  Cell(path:"photos/IMG_6143.jpeg", label:"IMG_6143 · 19:57", group:"JAPANESE ?"),
  Cell(path:"photos/IMG_6144.jpeg", label:"IMG_6144 · 19:57", group:"JAPANESE ?"),
  Cell(path:"photos/IMG_6145.jpeg", label:"IMG_6145 · 19:57", group:"JAPANESE ?"),
  Cell(path:"photos/IMG_6146.jpeg", label:"IMG_6146 · 19:57", group:"JAPANESE ?"),
]

func orientedImage(_ path: String) -> CGImage? {
    guard let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { return nil }
    let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any]
    let o = (props?[kCGImagePropertyOrientation] as? UInt32) ?? 1
    if o == 1 { return img }
    let w = img.width, h = img.height
    let swap = (o >= 5)
    let cw = swap ? h : w, ch = swap ? w : h
    guard let ctx = CGContext(data: nil, width: cw, height: ch, bitsPerComponent: 8, bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return img }
    switch o {
    case 3: ctx.translateBy(x: CGFloat(cw), y: CGFloat(ch)); ctx.rotate(by: .pi)
    case 6: ctx.translateBy(x: CGFloat(cw), y: 0); ctx.rotate(by: .pi/2)
    case 8: ctx.translateBy(x: 0, y: CGFloat(ch)); ctx.rotate(by: -.pi/2)
    default: break
    }
    ctx.draw(img, in: CGRect(x: 0, y: 0, width: w, height: h))
    return ctx.makeImage()
}

func drawText(_ ctx: CGContext, _ s: String, x: CGFloat, y: CGFloat, size: CGFloat, bold: Bool, color: CGColor) {
    let font = CTFontCreateWithName((bold ? "HelveticaNeue-Bold" : "HelveticaNeue") as CFString, size, nil)
    let attr: [NSAttributedString.Key: Any] = [
        NSAttributedString.Key(kCTFontAttributeName as String): font,
        NSAttributedString.Key(kCTForegroundColorAttributeName as String): color,
    ]
    let line = CTLineCreateWithAttributedString(NSAttributedString(string: s, attributes: attr))
    ctx.textPosition = CGPoint(x: x, y: y)
    CTLineDraw(line, ctx)
}

let cols = 4, rows = 2
let margin: CGFloat = 22, title: CGFloat = 46, gap: CGFloat = 12
let cellW: CGFloat = 320, imgH: CGFloat = 240, labelH: CGFloat = 30
let cellH = imgH + labelH
let W = Int(margin*2 + CGFloat(cols)*cellW + CGFloat(cols-1)*gap)
let H = Int(margin*2 + title + CGFloat(rows)*cellH + CGFloat(rows-1)*gap)

guard let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: 0,
    space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { exit(1) }
// bg
ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x:0,y:0,width:W,height:H))
// CG origin is bottom-left; we place rows from top
let top = CGFloat(H) - margin
// title
drawText(ctx, "Vancouver trip (Apr 19) — anyone remember these places?", x: margin, y: top - 30, size: 20, bold: true, color: CGColor(red:0.09,green:0.09,blue:0.1,alpha:1))

for (i, c) in cells.enumerated() {
    let col = i % cols, row = i / cols
    let cx = margin + CGFloat(col)*(cellW+gap)
    let cyTop = top - title - CGFloat(row)*(cellH+gap)      // top of this cell
    let imgRect = CGRect(x: cx, y: cyTop - imgH, width: cellW, height: imgH)
    // group tag color
    let isCafe = c.group.hasPrefix("CAFE")
    let tagColor = isCafe ? CGColor(red:0.55,green:0.35,blue:0.12,alpha:1) : CGColor(red:0.12,green:0.45,blue:0.3,alpha:1)
    // image aspect-fill, clipped to imgRect
    if let img = orientedImage(c.path) {
        let iw = CGFloat(img.width), ih = CGFloat(img.height)
        let scale = max(imgRect.width/iw, imgRect.height/ih)
        let dw = iw*scale, dh = ih*scale
        let dx = imgRect.midX - dw/2, dy = imgRect.midY - dh/2
        ctx.saveGState(); ctx.clip(to: imgRect); ctx.draw(img, in: CGRect(x:dx,y:dy,width:dw,height:dh)); ctx.restoreGState()
    } else {
        ctx.setFillColor(CGColor(gray:0.9,alpha:1)); ctx.fill(imgRect)
    }
    // frame
    ctx.setStrokeColor(CGColor(gray:0.8,alpha:1)); ctx.setLineWidth(1); ctx.stroke(imgRect)
    // label
    drawText(ctx, c.label, x: cx+2, y: cyTop - imgH - 20, size: 12.5, bold: false, color: CGColor(gray:0.35,alpha:1))
    drawText(ctx, c.group, x: cx+2, y: cyTop - imgH - 34, size: 12.5, bold: true, color: tagColor)
}

guard let out = ctx.makeImage() else { exit(1) }
let outURL = URL(fileURLWithPath: "vancouver-unknowns-collage.png")
guard let dest = CGImageDestinationCreateWithURL(outURL as CFURL, UTType.png.identifier as CFString, 1, nil) else { exit(1) }
CGImageDestinationAddImage(dest, out, nil)
CGImageDestinationFinalize(dest)
print("wrote vancouver-unknowns-collage.png (\(W)x\(H))")
