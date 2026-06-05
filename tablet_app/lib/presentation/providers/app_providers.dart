import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:in_person_test_tablet/data/repositories/ble_hub_repository_impl.dart';
import 'package:in_person_test_tablet/data/repositories/in_person_test_repository_impl.dart';
import 'package:in_person_test_tablet/domain/repositories/ble_hub_repository.dart';
import 'package:in_person_test_tablet/domain/repositories/in_person_test_repository.dart';

final bleHubRepositoryProvider = Provider<BleHubRepository>((ref) {
  final hub = BleHubRepositoryImpl();
  ref.onDispose(hub.dispose);
  return hub;
});

final inPersonTestRepositoryProvider = Provider<InPersonTestRepository>(
  (ref) => InPersonTestRepositoryImpl(),
);
