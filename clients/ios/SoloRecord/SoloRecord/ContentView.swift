import SwiftUI
import WebKit

struct ContentView: View {
    var body: some View {
        SoloRecordWebView(url: URL(string: serverURL())!)
            .ignoresSafeArea(.container, edges: .bottom)
    }
}

private func serverURL() -> String {
    if let bundled = Bundle.main.object(forInfoDictionaryKey: "SoloRecordServerURL") as? String,
       bundled.hasPrefix("http") {
        return bundled
    }
    return "http://127.0.0.1:8000"
}

struct SoloRecordWebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.allowsInlineMediaPlayback = true
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.load(URLRequest(url: url))
        return view
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

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
