import 'package:flutter_test/flutter_test.dart';
import 'package:in_person_test_tablet/domain/entities/physiological_snapshot.dart';

void main() {
  test('PhysiologicalSnapshot flags reflect populated fields', () {
    final snap = PhysiologicalSnapshot(
      timestamp: DateTime(2026, 6, 3),
      powerW: 200,
      heartRateBpm: 140,
      rrIntervalsMs: const [800, 820],
      coreTempC: 37.5,
    );
    expect(snap.hasPower, isTrue);
    expect(snap.hasHeartRate, isTrue);
    expect(snap.hasRr, isTrue);
    expect(snap.hasCoreTemp, isTrue);
  });
}
