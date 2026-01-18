import SwiftUI

struct AuthView: View {
    @EnvironmentObject var authManager: AuthManager
    @State private var email = ""
    @State private var password = ""
    @State private var isSignUp = false
    @State private var isLoading = false
    @State private var errorMessage: String?
    
    var body: some View {
        NavigationStack {
            ZStack {
                // Background gradient
                LinearGradient(
                    colors: [Color.red.opacity(0.8), Color.orange.opacity(0.6)],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .ignoresSafeArea()
                
                VStack(spacing: 32) {
                    Spacer()
                    
                    // Logo and Title
                    VStack(spacing: 16) {
                        Image(systemName: "play.rectangle.fill")
                            .font(.system(size: 80))
                            .foregroundStyle(.white)
                        
                        Text("WatchLater")
                            .font(.system(size: 42, weight: .bold, design: .rounded))
                            .foregroundStyle(.white)
                        
                        Text("Save YouTube summaries to Notion")
                            .font(.subheadline)
                            .foregroundStyle(.white.opacity(0.8))
                    }
                    
                    Spacer()
                    
                    // Form Card
                    VStack(spacing: 20) {
                        // Google Sign-In Button
                        Button(action: signInWithGoogle) {
                            HStack(spacing: 12) {
                                if authManager.isGoogleSignInProgress {
                                    ProgressView()
                                        .tint(.gray)
                                } else {
                                    // Google "G" logo using SF Symbol
                                    Image(systemName: "g.circle.fill")
                                        .font(.title2)
                                        .foregroundStyle(.blue, .blue.opacity(0.2))
                                    Text("Continue with Google")
                                        .fontWeight(.medium)
                                        .foregroundStyle(.primary)
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(.white)
                            .cornerRadius(12)
                        }
                        .disabled(isLoading || authManager.isGoogleSignInProgress)
                        
                        // Divider
                        HStack(spacing: 12) {
                            Rectangle()
                                .fill(.white.opacity(0.3))
                                .frame(height: 1)
                            Text("or")
                                .font(.caption)
                                .foregroundStyle(.white.opacity(0.7))
                            Rectangle()
                                .fill(.white.opacity(0.3))
                                .frame(height: 1)
                        }
                        
                        // Email/Password Fields
                        VStack(spacing: 16) {
                            TextField("Email", text: $email)
                                .textFieldStyle(.plain)
                                .padding()
                                .background(.white.opacity(0.2))
                                .cornerRadius(12)
                                .foregroundStyle(.white)
                                .autocapitalization(.none)
                                .keyboardType(.emailAddress)
                            
                            SecureField("Password", text: $password)
                                .textFieldStyle(.plain)
                                .padding()
                                .background(.white.opacity(0.2))
                                .cornerRadius(12)
                                .foregroundStyle(.white)
                        }
                        
                        if let error = errorMessage {
                            Text(error)
                                .font(.caption)
                                .foregroundStyle(.red)
                                .padding(.horizontal)
                                .multilineTextAlignment(.center)
                        }
                        
                        Button(action: authenticate) {
                            HStack {
                                if isLoading {
                                    ProgressView()
                                        .tint(.red)
                                } else {
                                    Text(isSignUp ? "Create Account" : "Sign In")
                                        .fontWeight(.semibold)
                                }
                            }
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(.white)
                            .foregroundStyle(.red)
                            .cornerRadius(12)
                        }
                        .disabled(isLoading || email.isEmpty || password.isEmpty || authManager.isGoogleSignInProgress)
                        
                        Button(action: { isSignUp.toggle() }) {
                            Text(isSignUp ? "Already have an account? Sign In" : "Don't have an account? Sign Up")
                                .font(.footnote)
                                .foregroundStyle(.white.opacity(0.9))
                        }
                    }
                    .padding(24)
                    .background(.ultraThinMaterial)
                    .cornerRadius(24)
                    .padding(.horizontal, 24)
                    
                    Spacer()
                }
            }
        }
    }
    
    private func authenticate() {
        isLoading = true
        errorMessage = nil
        
        Task {
            do {
                if isSignUp {
                    try await authManager.signUp(email: email, password: password)
                } else {
                    try await authManager.signIn(email: email, password: password)
                }
            } catch {
                errorMessage = error.localizedDescription
            }
            isLoading = false
        }
    }
    
    private func signInWithGoogle() {
        errorMessage = nil
        
        Task {
            do {
                try await authManager.signInWithGoogle()
            } catch {
                // Don't show error for cancelled sign-in
                if case GoogleSignInError.cancelled = error {
                    return
                }
                errorMessage = error.localizedDescription
            }
        }
    }
}

#Preview {
    AuthView()
        .environmentObject(AuthManager())
}
