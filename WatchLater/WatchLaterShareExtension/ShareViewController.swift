import UIKit
import SwiftUI

class ShareViewController: UIViewController {
    
    override func viewDidLoad() {
        super.viewDidLoad()
        
        // Extract the shared URL
        extractSharedURL { [weak self] url in
            guard let self = self, let url = url else {
                self?.showError("Could not get URL")
                return
            }
            
            // Show the share UI
            self.showShareUI(url: url)
        }
    }
    
    private func extractSharedURL(completion: @escaping (String?) -> Void) {
        guard let extensionItem = extensionContext?.inputItems.first as? NSExtensionItem,
              let attachments = extensionItem.attachments else {
            completion(nil)
            return
        }
        
        // Try to get URL
        for attachment in attachments {
            if attachment.hasItemConformingToTypeIdentifier("public.url") {
                attachment.loadItem(forTypeIdentifier: "public.url", options: nil) { item, error in
                    DispatchQueue.main.async {
                        if let url = item as? URL {
                            completion(url.absoluteString)
                        } else {
                            completion(nil)
                        }
                    }
                }
                return
            }
            
            // Also try plain text (YouTube sometimes shares as text)
            if attachment.hasItemConformingToTypeIdentifier("public.plain-text") {
                attachment.loadItem(forTypeIdentifier: "public.plain-text", options: nil) { item, error in
                    DispatchQueue.main.async {
                        if let text = item as? String, text.contains("youtu") {
                            completion(text)
                        } else {
                            completion(nil)
                        }
                    }
                }
                return
            }
        }
        
        completion(nil)
    }
    
    private func showShareUI(url: String) {
        // Check if user is authenticated
        let sharedDefaults = UserDefaults(suiteName: "group.com.watchlater.app")
        guard let token = sharedDefaults?.string(forKey: "supabase_access_token") else {
            showError("Please sign in to WatchLater first")
            return
        }
        
        // Create SwiftUI view
        let shareView = ShareExtensionView(
            url: url,
            onSave: { [weak self] in
                self?.summarizeAndSave(url: url, token: token)
            },
            onCancel: { [weak self] in
                self?.extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
            }
        )
        
        let hostingController = UIHostingController(rootView: shareView)
        hostingController.view.backgroundColor = .clear
        
        addChild(hostingController)
        view.addSubview(hostingController.view)
        hostingController.view.translatesAutoresizingMaskIntoConstraints = false
        
        NSLayoutConstraint.activate([
            hostingController.view.topAnchor.constraint(equalTo: view.topAnchor),
            hostingController.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            hostingController.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            hostingController.view.trailingAnchor.constraint(equalTo: view.trailingAnchor)
        ])
        
        hostingController.didMove(toParent: self)
    }
    
    private func summarizeAndSave(url: String, token: String) {
        // Show loading - update UI through the hosted SwiftUI view
        
        Task {
            do {
                let result = try await callSummarizeAPI(url: url, token: token)
                
                await MainActor.run {
                    if result.success {
                        self.showSuccess(title: result.title ?? "Summary saved!")
                    } else {
                        self.showError(result.error ?? "Failed to save")
                    }
                }
            } catch {
                await MainActor.run {
                    self.showError(error.localizedDescription)
                }
            }
        }
    }
    
    private func callSummarizeAPI(url: String, token: String) async throws -> SummarizeResult {
        let endpoint = URL(string: "https://watchlater.up.railway.app/summarize")!
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 60
        
        let body = ["url": url]
        request.httpBody = try JSONEncoder().encode(body)
        
        let (data, _) = try await URLSession.shared.data(for: request)
        return try JSONDecoder().decode(SummarizeResult.self, from: data)
    }
    
    private func showSuccess(title: String) {
        let alert = UIAlertController(title: "✅ Saved!", message: title, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "Done", style: .default) { [weak self] _ in
            self?.extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
        })
        present(alert, animated: true)
    }
    
    private func showError(_ message: String) {
        let alert = UIAlertController(title: "Error", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "OK", style: .cancel) { [weak self] _ in
            self?.extensionContext?.cancelRequest(withError: NSError(domain: "WatchLater", code: 1))
        })
        present(alert, animated: true)
    }
}

// MARK: - SwiftUI Share View

struct ShareExtensionView: View {
    let url: String
    let onSave: () -> Void
    let onCancel: () -> Void
    
    @State private var isLoading = false
    
    var body: some View {
        VStack(spacing: 0) {
            Spacer()
            
            VStack(spacing: 20) {
                // Header
                HStack {
                    Button("Cancel") {
                        onCancel()
                    }
                    .foregroundStyle(.secondary)
                    
                    Spacer()
                    
                    Text("WatchLater")
                        .font(.headline)
                    
                    Spacer()
                    
                    Button("Cancel") {
                        onCancel()
                    }
                    .opacity(0) // Balance the header
                }
                .padding(.horizontal)
                
                // URL Preview
                HStack {
                    Image(systemName: "play.rectangle.fill")
                        .font(.title)
                        .foregroundStyle(.red)
                    
                    Text(url)
                        .lineLimit(2)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    
                    Spacer()
                }
                .padding()
                .background(Color(.systemGray6))
                .cornerRadius(12)
                .padding(.horizontal)
                
                // Save Button
                Button(action: {
                    isLoading = true
                    onSave()
                }) {
                    HStack {
                        if isLoading {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Image(systemName: "sparkles")
                            Text("Summarize & Save")
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(
                        LinearGradient(
                            colors: [.red, .orange],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .foregroundStyle(.white)
                    .fontWeight(.semibold)
                    .cornerRadius(12)
                }
                .disabled(isLoading)
                .padding(.horizontal)
                .padding(.bottom, 20)
            }
            .padding(.vertical, 20)
            .background(Color(.systemBackground))
            .cornerRadius(20, corners: [.topLeft, .topRight])
        }
        .background(Color.black.opacity(0.3))
    }
}

// Corner radius helper
extension View {
    func cornerRadius(_ radius: CGFloat, corners: UIRectCorner) -> some View {
        clipShape(RoundedCorner(radius: radius, corners: corners))
    }
}

struct RoundedCorner: Shape {
    var radius: CGFloat = .infinity
    var corners: UIRectCorner = .allCorners
    
    func path(in rect: CGRect) -> Path {
        let path = UIBezierPath(
            roundedRect: rect,
            byRoundingCorners: corners,
            cornerRadii: CGSize(width: radius, height: radius)
        )
        return Path(path.cgPath)
    }
}

// MARK: - API Models

struct SummarizeResult: Codable {
    let success: Bool
    let title: String?
    let notionUrl: String?
    let error: String?
}
