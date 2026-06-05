import 'package:in_person_test_tablet/domain/entities/athlete_profile.dart';
import 'package:in_person_test_tablet/domain/entities/test_device_info.dart';
import 'package:in_person_test_tablet/domain/entities/test_type.dart';

/// Costruisce la busta JSON comune (CONTRATTO_JSON_test.md).
class TestEnvelopeBuilder {
  TestEnvelopeBuilder({
    required this.testType,
    required this.athlete,
    required this.testData,
    this.device,
    DateTime? timestamp,
  }) : timestamp = timestamp ?? DateTime.now();

  final InPersonTestType testType;
  final DateTime timestamp;
  final AthleteProfile athlete;
  final TestDeviceInfo? device;
  final Map<String, dynamic> testData;

  Map<String, dynamic> build() => {
        'test_type': testType.apiValue,
        'timestamp': timestamp.toIso8601String(),
        'athlete': athlete.toJson(),
        if (device != null) 'device': device!.toJson(),
        'test_data': testData,
      };
}
