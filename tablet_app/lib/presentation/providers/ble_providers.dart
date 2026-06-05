import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:in_person_test_tablet/domain/entities/connected_device.dart';
import 'package:in_person_test_tablet/domain/entities/discovered_device.dart';
import 'package:in_person_test_tablet/domain/entities/physiological_snapshot.dart';
import 'package:in_person_test_tablet/presentation/providers/app_providers.dart';

final bleReadyProvider = FutureProvider<bool>((ref) async {
  final hub = ref.watch(bleHubRepositoryProvider);
  return hub.ensureReady();
});

final discoveredDevicesProvider =
    StreamProvider<List<DiscoveredDevice>>((ref) {
  return ref.watch(bleHubRepositoryProvider).watchDiscoveredDevices();
});

final connectedDevicesProvider = StreamProvider<List<ConnectedDevice>>((ref) {
  return ref.watch(bleHubRepositoryProvider).watchConnectedDevices();
});

final liveSnapshotProvider = StreamProvider<PhysiologicalSnapshot>((ref) {
  return ref.watch(bleHubRepositoryProvider).watchLiveSnapshot();
});

final bleScanningProvider = StateProvider<bool>((ref) => false);
