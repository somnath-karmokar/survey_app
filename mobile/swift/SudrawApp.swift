// Sudraw iPhone app: a single SwiftUI file that opens https://sudraw.com in a WebView.
//
// Use: in Xcode, File > New > Project > iOS App (SwiftUI), name it "Sudraw",
// replace the generated <Name>App.swift and ContentView.swift with this file,
// then run on a device or simulator (an Apple developer account is needed to
// install on a phone or publish to the App Store).

import SwiftUI
import WebKit

@main
struct SudrawApp: App {
    var body: some Scene {
        WindowGroup {
            SudrawWebView()
                .ignoresSafeArea(edges: .bottom)
                .background(Color(red: 0x1d / 255, green: 0x18 / 255, blue: 0x14 / 255))
        }
    }
}

struct SudrawWebView: View {
    @StateObject private var model = WebViewModel()

    var body: some View {
        ZStack {
            WebView(model: model)
            if model.isLoading {
                ProgressView().scaleEffect(1.3)
            }
            if model.isOffline {
                VStack(spacing: 14) {
                    Text("You're offline").font(.title2).bold()
                    Text("Check your internet connection and try again.")
                        .multilineTextAlignment(.center)
                        .foregroundColor(.secondary)
                    Button("Try again") { model.reload() }
                        .buttonStyle(.borderedProminent)
                }
                .padding(32)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(.systemBackground))
            }
        }
    }
}

final class WebViewModel: NSObject, ObservableObject, WKNavigationDelegate, WKUIDelegate {
    static let home = URL(string: "https://sudraw.com")!
    static let allowedHosts = ["sudraw.com", "www.sudraw.com"]

    @Published var isLoading = true
    @Published var isOffline = false
    let webView: WKWebView

    override init() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()          // keeps users logged in between launches
        webView = WKWebView(frame: .zero, configuration: config)
        super.init()
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = true
        let refresh = UIRefreshControl()
        refresh.addTarget(self, action: #selector(pullToRefresh(_:)), for: .valueChanged)
        webView.scrollView.refreshControl = refresh
        webView.load(URLRequest(url: Self.home))
    }

    @objc private func pullToRefresh(_ sender: UIRefreshControl) {
        reload()
        sender.endRefreshing()
    }

    func reload() {
        isOffline = false
        if webView.url == nil {
            webView.load(URLRequest(url: Self.home))
        } else {
            webView.reload()
        }
    }

    // Keep sudraw.com inside the app; open other sites (adverts, PayPal...) in Safari.
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url, let host = url.host?.lowercased() else {
            decisionHandler(.allow); return
        }
        let inside = Self.allowedHosts.contains(host) || host.hasSuffix(".sudraw.com")
        if inside || url.scheme == "about" {
            decisionHandler(.allow)
        } else {
            UIApplication.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    // Links with target="_blank" open in the same view.
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if action.targetFrame == nil { webView.load(action.request) }
        return nil
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) { isLoading = true }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { isLoading = false; isOffline = false }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { failed(error) }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { failed(error) }

    private func failed(_ error: Error) {
        isLoading = false
        let code = (error as NSError).code
        if code == NSURLErrorNotConnectedToInternet || code == NSURLErrorNetworkConnectionLost || code == NSURLErrorTimedOut {
            isOffline = true
        }
    }
}

struct WebView: UIViewRepresentable {
    @ObservedObject var model: WebViewModel
    func makeUIView(context: Context) -> WKWebView { model.webView }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
