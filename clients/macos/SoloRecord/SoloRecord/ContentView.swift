import SwiftUI
import WebKit

struct ContentView: View {
    var body: some View {
        SoloRecordWebView(url: URL(string: serverURL())!)
    }
}

private func serverURL() -> String {
    if let bundled = Bundle.main.object(forInfoDictionaryKey: "SoloRecordServerURL") as? String,
       bundled.hasPrefix("http") {
        return bundled
    }
    return "https://record.uino.com"
}

struct SoloRecordWebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.load(URLRequest(url: url))
        return view
    }

    func updateNSView(_ webView: WKWebView, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction) async -> WKNavigationActionPolicy {
            guard let url = navigationAction.request.url else { return .allow }
            if ["http", "https"].contains(url.scheme?.lowercased()) {
                return .allow
            }
            return .cancel
        }
    }
}
