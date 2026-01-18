import UIKit
import Social
import MobileCoreServices
import UniformTypeIdentifiers

class ShareViewController: UIViewController {
    
    private var urlToShare: String?
    
    override func viewDidLoad() {
        super.viewDidLoad()
        setupUI()
        extractURL()
    }
    
    private func setupUI() {
        view.backgroundColor = UIColor.black.withAlphaComponent(0.5)
        
        let card = UIView()
        card.backgroundColor = .systemBackground
        card.layer.cornerRadius = 16
        card.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(card)
        
        let stackView = UIStackView()
        stackView.axis = .vertical
        stackView.spacing = 16
        stackView.alignment = .center
        stackView.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(stackView)
        
        // Icon
        let iconView = UIImageView(image: UIImage(systemName: "sparkles"))
        iconView.tintColor = .systemOrange
        iconView.contentMode = .scaleAspectFit
        iconView.widthAnchor.constraint(equalToConstant: 48).isActive = true
        iconView.heightAnchor.constraint(equalToConstant: 48).isActive = true
        stackView.addArrangedSubview(iconView)
        
        // Title
        let titleLabel = UILabel()
        titleLabel.text = "Saving to Notion..."
        titleLabel.font = .systemFont(ofSize: 18, weight: .semibold)
        titleLabel.textAlignment = .center
        stackView.addArrangedSubview(titleLabel)
        
        // Activity indicator
        let spinner = UIActivityIndicatorView(style: .medium)
        spinner.startAnimating()
        stackView.addArrangedSubview(spinner)
        
        NSLayoutConstraint.activate([
            card.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            card.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            card.widthAnchor.constraint(equalToConstant: 280),
            card.heightAnchor.constraint(equalToConstant: 160),
            
            stackView.centerXAnchor.constraint(equalTo: card.centerXAnchor),
            stackView.centerYAnchor.constraint(equalTo: card.centerYAnchor),
        ])
    }
    
    private func extractURL() {
        guard let item = extensionContext?.inputItems.first as? NSExtensionItem,
              let attachments = item.attachments else {
            complete(success: false, message: "No content found")
            return
        }
        
        for attachment in attachments {
            if attachment.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                attachment.loadItem(forTypeIdentifier: UTType.url.identifier, options: nil) { [weak self] item, _ in
                    if let url = item as? URL {
                        self?.urlToShare = url.absoluteString
                        self?.sendToAPI()
                    }
                }
                return
            }
            
            if attachment.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                attachment.loadItem(forTypeIdentifier: UTType.plainText.identifier, options: nil) { [weak self] item, _ in
                    if let text = item as? String, text.contains("youtube.com") || text.contains("youtu.be") {
                        self?.urlToShare = text
                        self?.sendToAPI()
                    }
                }
                return
            }
        }
        
        complete(success: false, message: "No YouTube URL found")
    }
    
    private func sendToAPI() {
        guard let url = urlToShare,
              let token = UserDefaults(suiteName: "group.com.watchlater.app")?.string(forKey: "access_token") else {
            complete(success: false, message: "Please sign in first")
            return
        }
        
        let apiURL = URL(string: "https://watchlater.up.railway.app/summarize")!
        var request = URLRequest(url: apiURL)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try? JSONEncoder().encode(["url": url])
        
        URLSession.shared.dataTask(with: request) { [weak self] data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    self?.complete(success: false, message: error.localizedDescription)
                    return
                }
                
                if let data = data,
                   let response = try? JSONDecoder().decode(SummaryResponse.self, from: data),
                   response.success {
                    self?.complete(success: true, message: response.title ?? "Saved!")
                } else {
                    self?.complete(success: false, message: "Failed to save")
                }
            }
        }.resume()
    }
    
    private func complete(success: Bool, message: String) {
        DispatchQueue.main.asyncAfter(deadline: .now() + (success ? 1.0 : 2.0)) {
            self.extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
        }
    }
}

// Response model
struct SummaryResponse: Codable {
    let success: Bool
    let title: String?
    let notionUrl: String?
    let error: String?
}
