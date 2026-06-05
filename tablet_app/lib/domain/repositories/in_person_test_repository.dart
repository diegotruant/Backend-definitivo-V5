/// Invio busta test al backend (fase successiva).
abstract class InPersonTestRepository {
  Future<Map<String, dynamic>> submitTest(Map<String, dynamic> envelope);
}
