// gpu-maid-bar — first-party macOS menu bar app for the gpu-maid agent.
//
// One file, AppKit only, zero third-party dependencies. Build:
//     swiftc -O gpumaid-bar.swift -o gpumaid-bar
// or use scripts/build_macos_app.sh to get a proper gpumaid-bar.app bundle.
//
// Reads the same config as the CLI: $GPUMAID_URL / ~/.gpumaid/config.json
// (written by `gpumaid connect`), $GPUMAID_TOKEN.
//
// Menu bar shows live GPU memory / utilization / temperature (color-coded:
// green / orange / red as free VRAM shrinks, purple when the master switch
// is off, gray when the agent is unreachable). The menu offers one-click
// wake/sleep per resident, the make-room queue, per-process VRAM, recent
// events and the master switch.

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

// MARK: - app delegate

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    private let url = agentURL()
    private var events: [[String: Any]] = []

    func applicationDidFinishLaunching(_ note: Notification) {
        statusItem.button?.title = "maid …"
        refresh()
        Timer.scheduledTimer(withTimeInterval: 5.0, repeats: true) { [weak self] _ in
            self?.refresh()
        }
    }

    // MARK: networking

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

    private func post(_ path: String) {
        // fire-and-forget: make-room can block for a while on the server,
        // the bar must never wait for it.
        URLSession.shared.dataTask(with: request(path, timeout: 60)) { _, _, _ in
        }.resume()
    }

    private func refresh() {
        get("/list") { [weak self] data in
            self?.apply(data: data)
        }
        get("/events?n=8") { [weak self] data in
            guard let self = self,
                  let ev = data?["events"] as? [[String: Any]] else { return }
            self.events = ev
        }
    }

    // MARK: rendering

    private func apply(data: [String: Any]?) {
        var title = "maid ✗"
        var color = NSColor.systemGray
        var gpuLine = "agent unreachable at \(url)"
        var gate: [String: Any]?
        var residents: [String: [String: Any]] = [:]
        var masterOff = false
        var apps: [[String: Any]] = []

        if let d = data {
            masterOff = (d["master_off"] as? Bool) ?? false
            gate = d["gate"] as? [String: Any]
            apps = (d["compute_apps"] as? [[String: Any]]) ?? []
            if let rs = d["residents"] as? [String: [String: Any]] {
                residents = rs
            }
            if let g = d["gpu"] as? [String: Any], let free = g["free_gb"] as? Double {
                if masterOff {
                    title = "maid 💤"
                    color = .systemPurple
                } else {
                    title = "GPU \(free)/\(g["total_gb"] ?? "?")G"
                    if let u = g["util_pct"] as? Int { title += " · \(u)%" }
                    if let t = g["temp_c"] as? Int { title += " · \(t)°C" }
                    color = free > 2 ? .systemGreen : (free > 0.5 ? .systemOrange : .systemRed)
                }
                gpuLine = "GPU free \(free) / \(g["total_gb"] ?? "?") GB"
            }
        }

        if let b = statusItem.button {
            b.attributedTitle = NSAttributedString(
                string: title, attributes: [.foregroundColor: color])
        }
        rebuildMenu(gpuLine: gpuLine, gate: gate, residents: residents,
                    masterOff: masterOff, apps: apps)
    }

    private func rebuildMenu(gpuLine: String, gate: [String: Any]?,
                             residents: [String: [String: Any]],
                             masterOff: Bool, apps: [[String: Any]]) {
        let m = NSMenu()
        m.autoenablesItems = false

        func header(_ title: String) {
            let i = m.addItem(withTitle: title, action: nil, keyEquivalent: "")
            i.isEnabled = false
        }
        func line(_ title: String, act: String? = nil, indent: Bool = false) {
            let i = m.addItem(
                withTitle: (indent ? "   " : "") + title,
                action: act == nil ? nil : #selector(runAction(_:)),
                keyEquivalent: "")
            i.target = act == nil ? nil : self
            i.representedObject = act
            i.isEnabled = act != nil
        }

        header(gpuLine)
        if let g = gate, let holder = g["holder"] as? String, !holder.isEmpty {
            let waiting = (g["waiting"] as? [String])?.joined(separator: ", ") ?? ""
            header("making room: \(holder)" + (waiting.isEmpty ? "" : " (waiting: \(waiting))"))
        }
        m.addItem(.separator())

        for name in residents.keys.sorted() {
            guard let r = residents[name] else { continue }
            let alive = (r["alive"] as? Bool) ?? false
            let suspended = (r["suspended"] as? Bool) ?? false
            let proto = r["protocol"] as? String ?? "process"
            let vram = r["vram_gb"] as? Int ?? 0
            let dot = alive ? "●" : (suspended ? "○" : "✕")
            line("\(dot) \(name) · \(proto) · \(vram)G")
            if alive || suspended { line("   wake \(name)", act: "/wake/\(name)", indent: true) }
            if alive { line("   sleep \(name)", act: "/sleep/\(name)", indent: true) }
            if let desc = r["desc"] as? String, !desc.isEmpty {
                line("   \(desc)")
            }
        }

        if !apps.isEmpty {
            m.addItem(.separator())
            header("holding VRAM (\(apps.count))")
            for a in apps.prefix(12) {
                line("   \(a["name"] as? String ?? "?") · \(a["mb"] as? Int ?? 0) MB · pid \(a["pid"] as? String ?? "?")")
            }
        }

        if !events.isEmpty {
            m.addItem(.separator())
            header("recent")
            for e in events.suffix(8) {
                let ts = e["ts"] as? String ?? ""
                let msg = e["msg"] as? String ?? ""
                line("   \(ts)  \(msg)")
            }
        }

        m.addItem(.separator())
        line(masterOff ? "master ON" : "master OFF (give the GPU back)",
             act: masterOff ? "/master/on" : "/master/off")
        m.addItem(.separator())
        let quit = m.addItem(withTitle: "quit gpu-maid",
                             action: #selector(NSApplication.terminate(_:)),
                             keyEquivalent: "q")
        quit.isEnabled = true

        statusItem.menu = m
    }

    @objc private func runAction(_ sender: NSMenuItem) {
        guard let path = sender.representedObject as? String else { return }
        post(path)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
            self?.refresh()
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.run()
