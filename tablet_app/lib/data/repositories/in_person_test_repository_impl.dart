import 'dart:convert';

import 'package:in_person_test_tablet/core/config/app_config.dart';
import 'package:in_person_test_tablet/domain/repositories/in_person_test_repository.dart';

/// Client HTTP minimale per invio busta test (da completare con dio/http).
class InPersonTestRepositoryImpl implements InPersonTestRepository {
  InPersonTestRepositoryImpl({AppConfig? config})
      : _baseUrl = (config ?? AppConfig.current).backendBaseUrl;

  final String _baseUrl;

  @override
  Future<Map<String, dynamic>> submitTest(
    Map<String, dynamic> envelope,
  ) async {
    // Placeholder: integrazione API nel prossimo step.
    return {
      'status': 'pending',
      'message': 'Backend non ancora collegato',
      'endpoint': '$_baseUrl/in-person-test',
      'payload_preview': jsonEncode(envelope).length,
    };
  }
}
