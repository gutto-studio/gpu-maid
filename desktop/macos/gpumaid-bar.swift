// gpu-maid-bar — first-party macOS menu bar app for the gpu-maid agent.
//
// One file, AppKit only, zero third-party dependencies. Build:
//     swiftc -O gpumaid-bar.swift -o gpumaid-bar
// or use scripts/build_macos_app.sh to get a proper gpumaid-bar.app bundle.
//
// Interaction model: the menu bar shows a compact color-coded indicator
// (colored dot + free VRAM); clicking opens a card-style panel with the
// VRAM gauge, the resident roster with one-click wake/sleep, the make-room
// queue, per-process VRAM and recent events.
//
// Reads the same config as the CLI: $GPUMAID_URL / ~/.gpumaid/config.json
// (written by `gpumaid connect`), $GPUMAID_TOKEN. Optional config key
// "dashboard": a URL opened by the "machine room" footer link.

import AppKit

// MARK: - configuration

func agentURL() -> String {
    let env = ProcessInfo.processInfo.environment
    if let u = env["GPUMAID_URL"], !u.isEmpty {
        return u.hasSuffix("/") ? String(u.dropLast()) : u
    }
    let cfg = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".gpumaid/config.json")
    if let data = try? Data(contentsOf: cfg),
       let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
       let u = obj["url"] as? String, !u.isEmpty {
        return u.hasSuffix("/") ? String(u.dropLast()) : u
    }
    return "http://127.0.0.1:9700"
}

func maidToken() -> String? {
    let t = ProcessInfo.processInfo.environment["GPUMAID_TOKEN"] ?? ""
    return t.isEmpty ? nil : t
}

func dashboardURL() -> String? {
    if let u = ProcessInfo.processInfo.environment["GPUMAID_DASHBOARD"], !u.isEmpty {
        return u
    }
    let cfg = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent(".gpumaid/config.json")
    if let data = try? Data(contentsOf: cfg),
       let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
       let u = obj["dashboard"] as? String, !u.isEmpty {
        return u
    }
    return nil
}

// MARK: - VRAM gauge (custom-drawn rounded bar)

final class VRAMBarView: NSView {
    var fraction: CGFloat = 0 { didSet { needsDisplay = true } }

    override var intrinsicContentSize: NSSize {
        NSSize(width: NSView.noIntrinsicMetric, height: 8)
    }

    override func draw(_ dirtyRect: NSRect) {
        let track = NSBezierPath(roundedRect: bounds, xRadius: 4, yRadius: 4)
        NSColor.systemGray.withAlphaComponent(0.22).setFill()
        track.fill()
        let frac = min(max(fraction, 0), 1)
        guard frac > 0.005 else { return }
        let w = max(bounds.width * frac, 8)
        let fill = NSBezierPath(
            roundedRect: NSRect(x: 0, y: 0, width: w, height: bounds.height),
            xRadius: 4, yRadius: 4)
        NSColor(red: 0.93, green: 0.28, blue: 0.60, alpha: 1).setFill() // #ec4899
        fill.fill()
    }
}

// MARK: - panel view controller (the card)

final class PanelVC: NSViewController {
    private let status = NSTextField(labelWithString: "…")
    private let bar = VRAMBarView()
    private let caption = NSTextField(labelWithString: "")
    private let telemetry = NSTextField(labelWithString: "")
    private let rows = NSStackView()
    private let eventsStack = NSStackView()
    var onRefresh: (() -> Void)?
    var onResize: ((NSSize) -> Void)?

    override func loadView() {
        let v = NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 360))
        v.wantsLayer = true

        let outer = NSStackView()
        outer.orientation = .vertical
        outer.alignment = .leading
        outer.spacing = 4
        outer.edgeInsets = NSEdgeInsets(top: 12, left: 14, bottom: 10, right: 14)
        outer.translatesAutoresizingMaskIntoConstraints = false
        v.addSubview(outer)
        NSLayoutConstraint.activate([
            outer.leadingAnchor.constraint(equalTo: v.leadingAnchor),
            outer.trailingAnchor.constraint(equalTo: v.trailingAnchor),
            outer.topAnchor.constraint(equalTo: v.topAnchor),
            outer.bottomAnchor.constraint(lessThanOrEqualTo: v.bottomAnchor, constant: -4),
            v.widthAnchor.constraint(equalToConstant: 280),
        ])

        func label(_ text: String, size: CGFloat = 13,
                   color: NSColor = .labelColor, bold: Bool = false) -> NSTextField {
            let t = NSTextField(labelWithString: text)
            t.font = bold ? .systemFont(ofSize: size, weight: .semibold)
                          : .systemFont(ofSize: size)
            t.textColor = color
            return t
        }

        // in-progress section
        outer.addView(NSStackView(views: [
            label("In progress", size: 13, bold: true)
        ]), in: .top)
        outer.addView(status, in: .top)

        // residents section
        outer.addView(label("Residents", size: 13, bold: true), in: .top)
        bar.translatesAutoresizingMaskIntoConstraints = false
        bar.widthAnchor.constraint(equalToConstant: 252).isActive = true
        outer.addView(bar, in: .top)
        outer.addView(caption, in: .top)
        outer.addView(telemetry, in: .top)
        rows.orientation = .vertical
        rows.alignment = .leading
        rows.spacing = 2
        outer.addView(rows, in: .top)

        // events section
        eventsStack.orientation = .vertical
        eventsStack.alignment = .leading
        eventsStack.spacing = 2
        outer.addView(eventsStack, in: .top)

        view = v
    }

    // MARK: state application

    func apply(data: [String: Any]?, events: [[String: Any]]) {
        guard let d = data else {
            status.stringValue = "agent unreachable"
            caption.stringValue = ""
            clear(rows)
            return
        }

        // activity: gate queue first, else who is on the job
        let residentsDict = d["residents"] as? [String: [String: Any]] ?? [:]
        let gate = d["gate"] as? [String: Any]
        let aliveList = residentsDict
            .filter { ($0.value["alive"] as? Bool) == true }
            .keys.sorted()
        if let holder = gate?["holder"] as? String, !holder.isEmpty {
            let waiting = (gate?["waiting"] as? [String])?.joined(separator: ", ") ?? ""
            status.stringValue = "making room: \(holder)"
                + (waiting.isEmpty ? "" : "  (waiting: \(waiting))")
        } else if let off = d["master_off"] as? Bool, off {
            status.stringValue = "master off — the house is asleep"
        } else if !aliveList.isEmpty {
            status.stringValue = "on the job: " + aliveList.joined(separator: ", ")
        } else {
            status.stringValue = "All quiet — the house is calm"
        }

        // vram gauge: used / total, plus temperature & utilization
        let g = d["gpu"] as? [String: Any]
        let free = g?["free_gb"] as? Double
        let total = g?["total_gb"] as? Double
        if let f = free, let t = total, t > 0 {
            bar.fraction = CGFloat((t - f) / t)
            caption.stringValue = String(format: "used %.2fG · free %.2fG", t - f, f)
        } else {
            bar.fraction = 0
            caption.stringValue = "GPU telemetry unavailable"
        }
        var tele: [String] = []
        if let temp = g?["temp_c"] as? Int { tele.append("\(temp)°C") }
        if let util = g?["util_pct"] as? Int { tele.append("util \(util)%") }
        telemetry.stringValue = tele.joined(separator: " · ")
        telemetry.textColor = .secondaryLabelColor
        telemetry.font = .systemFont(ofSize: 11)
        telemetry.isHidden = tele.isEmpty

        // resident rows
        clear(rows)
        var anyShown = false
        for name in residentsDict.keys.sorted() {
            guard let r = residentsDict[name] else { continue }
            anyShown = true
            rows.addView(row(name: name, r: r), in: .top)
        }
        if !anyShown {
            rows.addView(label("no residents configured", size: 12), in: .top)
        }

        // events
        clear(eventsStack)
        for e in events.suffix(3) {
            let ts = e["ts"] as? String ?? ""
            let msg = e["msg"] as? String ?? ""
            let t = NSTextField(labelWithString: "\(ts)  \(msg)")
            t.font = .systemFont(ofSize: 10)
            t.textColor = .secondaryLabelColor
            t.lineBreakMode = .byTruncatingTail
            t.maximumNumberOfLines = 1
            t.translatesAutoresizingMaskIntoConstraints = false
            t.widthAnchor.constraint(equalToConstant: 252).isActive = true
            eventsStack.addView(t, in: .top)
        }
        view.layoutSubtreeIfNeeded()
        onResize?(NSSize(width: 280, height: max(160, view.fittingSize.height)))
    }

    private func clear(_ s: NSStackView) {
        for v in s.arrangedSubviews { s.removeView(v) }
    }

    private func label(_ text: String, size: CGFloat = 13,
                       color: NSColor = .labelColor, bold: Bool = false) -> NSTextField {
        let t = NSTextField(labelWithString: text)
        t.font = bold ? .systemFont(ofSize: size, weight: .semibold)
                      : .systemFont(ofSize: size)
        t.textColor = color
        return t
    }

    private func row(name: String, r: [String: Any]) -> NSView {
        let line = NSStackView()
        line.orientation = .horizontal
        line.alignment = .centerY
        line.spacing = 6
        line.translatesAutoresizingMaskIntoConstraints = false
        line.widthAnchor.constraint(equalToConstant: 268).isActive = true

        let alive = (r["alive"] as? Bool) ?? false
        let suspended = (r["suspended"] as? Bool) ?? false
        let protocolName = r["protocol"] as? String ?? "process"
        let isAlways = protocolName == "always_on"

        let dot = NSTextField(labelWithString: alive ? "●" : (suspended ? "○" : "✕"))
        dot.textColor = alive ? .systemGreen : (suspended ? .systemGray : .systemRed)
        line.addView(dot, in: .top)

        let name_ = NSTextField(labelWithString: name)
        name_.font = .systemFont(ofSize: 13)
        name_.lineBreakMode = .byTruncatingTail
        name_.setContentCompressionResistancePriority(.defaultLow,
                                                      for: .horizontal)
        line.addView(name_, in: .top)

        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        line.addView(spacer, in: .top)

        // action button (right-aligned, like the mockup's play/pause);
        // rows without a possible action get no button at all
        let canSleep = alive && !isAlways
        let canWake = !alive && r["start"] != nil && protocolName != "always_on"
        guard canSleep || canWake else { return line }
        let btn = NSButton(title: canSleep ? "⏸" : "▶", target: self,
                           action: #selector(onAction(_:)))
        btn.bezelStyle = .rounded
        btn.controlSize = .small
        btn.font = .systemFont(ofSize: 11)
        btn.identifier = NSUserInterfaceItemIdentifier(
            "/\(canSleep ? "sleep" : "wake")/\(name)")
        line.addView(btn, in: .top)
        return line
    }

    @objc private func onAction(_ sender: NSButton) {
        guard let path = sender.identifier?.rawValue else { return }
        NotificationCenter.default.post(
            name: Notification.Name("GPUMaidAction"), object: path)
    }
}

// MARK: - app delegate

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let popover = NSPopover()
    private lazy var panel = PanelVC()
    private let url = agentURL()
    private var events: [[String: Any]] = []

    func applicationDidFinishLaunching(_ note: Notification) {
        popover.behavior = .transient
        popover.contentSize = NSSize(width: 280, height: 220)
        popover.contentViewController = panel
        panel.onResize = { [weak self] size in
            self?.popover.contentSize = size
        }

        let b = statusItem.button
        b?.title = "maid …"
        b?.toolTip = "gpu-maid"
        b?.action = #selector(togglePopover)
        b?.target = self

        NotificationCenter.default.addObserver(
            self, selector: #selector(onPanelAction(_:)),
            name: Notification.Name("GPUMaidAction"), object: nil)

        refresh()
        Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    @objc private func togglePopover() {
        if popover.isShown {
            popover.performClose(nil)
        } else {
            panel.apply(data: lastData, events: events)
            popover.show(relativeTo: statusItem.button!.bounds,
                         of: statusItem.button!, preferredEdge: .minY)
            refresh()
        }
    }

    @objc private func onPanelAction(_ note: Notification) {
        guard let path = note.object as? String else { return }
        var r = URLRequest(url: URL(string: url + path)!, timeoutInterval: 60)
        r.httpMethod = "POST"
        if let t = maidToken() {
            r.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization")
        }
        URLSession.shared.dataTask(with: r) { _, _, _ in }.resume()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            self?.refresh()
        }
    }

    private var lastData: [String: Any]?

    private func request(_ path: String, timeout: TimeInterval = 4) -> URLRequest {
        var r = URLRequest(url: URL(string: url + path)!, timeoutInterval: timeout)
        if let t = maidToken() {
            r.setValue("Bearer \(t)", forHTTPHeaderField: "Authorization")
        }
        return r
    }

    private func get(_ path: String, done: @escaping ([String: Any]?) -> Void) {
        URLSession.shared.dataTask(with: request(path)) { data, _, _ in
            let obj = (data.flatMap { try? JSONSerialization.jsonObject(with: $0) })
                as? [String: Any]
            DispatchQueue.main.async { done(obj) }
        }.resume()
    }

    private func refresh() {
        get("/list") { [weak self] data in
            guard let self = self else { return }
            self.lastData = data
            self.applyBar(data: data)
            if self.popover.isShown {
                self.panel.apply(data: data, events: self.events)
            }
        }
        get("/events?n=8") { [weak self] data in
            guard let self = self,
                  let ev = data?["events"] as? [[String: Any]] else { return }
            self.events = ev
            if self.popover.isShown {
                self.panel.apply(data: self.lastData, events: self.events)
            }
        }
    }

    private func applyBar(data: [String: Any]?) {
        var title = "⚠︎ maid"
        var color = NSColor.systemGray
        var tip = "gpu-maid: agent unreachable at \(url)"

        if let d = data {
            let masterOff = (d["master_off"] as? Bool) ?? false
            let g = d["gpu"] as? [String: Any]
            if masterOff {
                title = "💤"
                color = .systemPurple
                tip = "gpu-maid: master off — the GPU is the owner's"
            } else if let free = g?["free_gb"] as? Double {
                let total = g?["total_gb"] as? Double
                title = "● \(String(format: "%.1f", free))G"
                color = free > 2 ? .systemGreen
                    : (free > 0.5 ? .systemOrange : .systemRed)
                tip = "gpu-maid: free \(free) / \(total ?? -1) GB"
                if let u = g?["util_pct"] as? Int { tip += " · util \(u)%" }
                if let t = g?["temp_c"] as? Int { tip += " · \(t)°C" }
            }
        }
        if let b = statusItem.button {
            b.attributedTitle = NSAttributedString(
                string: title, attributes: [.foregroundColor: color])
            b.toolTip = tip
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
