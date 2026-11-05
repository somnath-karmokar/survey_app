// Sudraw iPhone app: opens https://sudraw.com full-screen in a web view.
//
// Use it in either:
//  - Swift Playgrounds (iPad or Mac): File > New App, replace the generated code with this file.
//  - Xcode (Mac): File > New > Project > iOS App (SwiftUI), replace the app's .swift file with this one.
// Installing on iPhones still needs Apple signing (Xcode, or TestFlight/App Store with a developer account).

import SwiftUI
import WebKit

@main
struct SudrawApp: App {
    var body: some Scene {
        WindowGroup {
            SudrawView()
        }
    }
}

struct SudrawView: View {
    @State private var isLoading = true
    @State private var loadFailed = false
    @State private var reloadToken = 0

    var body: some View {
        ZStack {
            Color(red: 0x1d / 255, green: 0x18 / 255, blue: 0x14 / 255).ignoresSafeArea()
            SudrawWebView(isLoading: $isLoading, loadFailed: $loadFailed, reloadToken: reloadToken)
            if isLoading && !loadFailed {
                ProgressView().tint(.white)
            }
            if loadFailed {
                VStack(spacing: 16) {
                    Text("You're offline").font(.title2).bold().foregroundColor(.white)
                    Text("Sudraw needs an internet connection.")
                        .foregroundColor(.white.opacity(0.7))
                    Button("Try again") {
                        loadFailed = false
                        isLoading = true
                        reloadToken += 1
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color(red: 0.97, green: 0.71, blue: 0.0))
                }
                .padding()
            }
        }
    }
}

struct SudrawWebView: UIViewRepresentable {
    static let home = URL(string: "https://sudraw.com")!

    @Binding var isLoading: Bool
    @Binding var loadFailed: Bool
    var reloadToken: Int

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true      // swipe to go back/forward
        webView.isOpaque = false
        webView.backgroundColor = .clear
        let refresh = UIRefreshControl()                        // pull down to reload
        refresh.addTarget(context.coordinator, action: #selector(Coordinator.reload(_:)), for: .valueChanged)
        webView.scrollView.refreshControl = refresh
        webView.load(URLRequest(url: Self.home))
        context.coordinator.lastReloadToken = reloadToken
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        if context.coordinator.lastReloadToken != reloadToken {
            context.coordinator.lastReloadToken = reloadToken
            webView.load(URLRequest(url: webView.url ?? Self.home))
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        let parent: SudrawWebView
        var lastReloadToken = 0

        init(_ parent: SudrawWebView) { self.parent = parent }

        @objc func reload(_ sender: UIRefreshControl) {
            (sender.superview?.superview as? WKWebView)?.reload()
            sender.endRefreshing()
        }

        // Keep sudraw.com inside the app; open every other site (and mail/phone links) outside it.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { return decisionHandler(.allow) }
            let host = url.host?.lowercased() ?? ""
            let isSudraw = host == "sudraw.com" || host.hasSuffix(".sudraw.com")
            let isWeb = url.scheme == "https" || url.scheme == "http"
            if action.targetFrame?.isMainFrame == false || isSudraw || (isWeb && action.navigationType != .linkActivated) {
                decisionHandler(.allow)          // sudraw pages, embedded frames (e.g. the survey offerwall)
            } else {
                UIApplication.shared.open(url)   // other sites, mailto:, tel: open in Safari / Mail / Phone
                decisionHandler(.cancel)
            }
        }

        // Links that ask for a new window (target="_blank") open in the same view.
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if action.targetFrame == nil, let url = action.request.url { webView.load(URLRequest(url: url)) }
            return nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            handle(error)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            handle(error)
        }

        private func handle(_ error: Error) {
            parent.isLoading = false
            if (error as NSError).code != NSURLErrorCancelled { parent.loadFailed = true }
        }
    }
}
