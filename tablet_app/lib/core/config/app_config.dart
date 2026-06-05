/// Configurazione globale dell'app (endpoint backend, feature flag).
class AppConfig {
  const AppConfig({
    this.backendBaseUrl = 'http://localhost:8000',
    this.useFakeBle = true,
  });

  /// URL base API Digital Twin (test in presenza).
  final String backendBaseUrl;

  /// Se true, usa hub BLE simulato (sviluppo senza hardware).
  final bool useFakeBle;

  static const AppConfig current = AppConfig();
}
