import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:in_person_test_tablet/core/routing/routes.dart';
import 'package:in_person_test_tablet/domain/entities/ble_connection_status.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';
import 'package:in_person_test_tablet/domain/entities/discovered_device.dart';
import 'package:in_person_test_tablet/presentation/providers/app_providers.dart';
import 'package:in_person_test_tablet/presentation/providers/ble_providers.dart';
import 'package:in_person_test_tablet/presentation/widgets/device_kind_icon.dart';
import 'package:in_person_test_tablet/presentation/widgets/live_metrics_panel.dart';

class DevicesScreen extends ConsumerStatefulWidget {
  const DevicesScreen({super.key});

  @override
  ConsumerState<DevicesScreen> createState() => _DevicesScreenState();
}

class _DevicesScreenState extends ConsumerState<DevicesScreen> {
  DeviceKind? _filterKind;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scanning = ref.watch(bleScanningProvider);
    final discovered = ref.watch(discoveredDevicesProvider);
    final connected = ref.watch(connectedDevicesProvider);
    final snapshot = ref.watch(liveSnapshotProvider);

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go(AppRoutes.home),
        ),
        title: const Text('Dispositivi BLE'),
      ),
      body: Row(
        children: [
          SizedBox(
            width: 280,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text('Filtro tipo', style: theme.textTheme.titleSmall),
                ),
                _FilterTile(
                  label: 'Tutti',
                  selected: _filterKind == null,
                  onTap: () => setState(() => _filterKind = null),
                ),
                for (final k in DeviceKind.values)
                  _FilterTile(
                    label: k.label,
                    icon: iconForDeviceKind(k),
                    selected: _filterKind == k,
                    onTap: () => setState(() => _filterKind = k),
                  ),
                const Spacer(),
                Padding(
                  padding: const EdgeInsets.all(16),
                  child: FilledButton.icon(
                    onPressed: () => _toggleScan(scanning),
                    icon: Icon(scanning ? Icons.stop : Icons.search),
                    label: Text(scanning ? 'Ferma scansione' : 'Avvia scansione'),
                  ),
                ),
              ],
            ),
          ),
          const VerticalDivider(width: 1),
          Expanded(
            flex: 2,
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Trovati', style: theme.textTheme.titleLarge),
                  const SizedBox(height: 12),
                  Expanded(
                    child: discovered.when(
                      data: (list) {
                        final filtered = _filterKind == null
                            ? list
                            : list.where((d) => d.kind == _filterKind).toList();
                        if (filtered.isEmpty) {
                          return Center(
                            child: Text(
                              scanning
                                  ? 'Ricerca in corso…'
                                  : 'Nessun dispositivo. Avvia la scansione.',
                              style: theme.textTheme.bodyLarge,
                            ),
                          );
                        }
                        return ListView.separated(
                          itemCount: filtered.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(height: 8),
                          itemBuilder: (context, i) =>
                              _DiscoveredTile(device: filtered[i]),
                        );
                      },
                      loading: () =>
                          const Center(child: CircularProgressIndicator()),
                      error: (e, _) => Center(child: Text('Errore: $e')),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const VerticalDivider(width: 1),
          Expanded(
            flex: 2,
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Collegati', style: theme.textTheme.titleLarge),
                  const SizedBox(height: 12),
                  Expanded(
                    child: connected.when(
                      data: (list) {
                        if (list.isEmpty) {
                          return const Center(
                            child: Text('Nessun dispositivo collegato'),
                          );
                        }
                        return ListView.separated(
                          itemCount: list.length,
                          separatorBuilder: (_, __) =>
                              const SizedBox(height: 8),
                          itemBuilder: (context, i) {
                            final d = list[i];
                            return ListTile(
                              leading: Icon(iconForDeviceKind(d.kind)),
                              title: Text(d.name),
                              subtitle: Text(
                                '${d.kind.label} · ${_statusLabel(d.status)}',
                              ),
                              trailing: d.isConnected
                                  ? IconButton(
                                      icon: const Icon(Icons.link_off),
                                      onPressed: () => ref
                                          .read(bleHubRepositoryProvider)
                                          .disconnect(d.id),
                                    )
                                  : null,
                            );
                          },
                        );
                      },
                      loading: () =>
                          const Center(child: CircularProgressIndicator()),
                      error: (e, _) => Center(child: Text('Errore: $e')),
                    ),
                  ),
                  const SizedBox(height: 16),
                  snapshot.when(
                    data: (s) => LiveMetricsPanel(snapshot: s),
                    loading: () => const SizedBox.shrink(),
                    error: (_, __) => const SizedBox.shrink(),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _toggleScan(bool scanning) async {
    final hub = ref.read(bleHubRepositoryProvider);
    if (scanning) {
      await hub.stopScan();
      ref.read(bleScanningProvider.notifier).state = false;
    } else {
      final ready = await hub.ensureReady();
      if (!ready && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Bluetooth non disponibile o spento'),
          ),
        );
        return;
      }
      await hub.startScan(kinds: _filterKind == null ? null : {_filterKind!});
      ref.read(bleScanningProvider.notifier).state = true;
    }
  }

  String _statusLabel(BleConnectionStatus s) => switch (s) {
        BleConnectionStatus.disconnected => 'disconnesso',
        BleConnectionStatus.connecting => 'connessione…',
        BleConnectionStatus.connected => 'connesso',
        BleConnectionStatus.error => 'errore',
      };
}

class _FilterTile extends StatelessWidget {
  const _FilterTile({
    required this.label,
    required this.selected,
    required this.onTap,
    this.icon,
  });

  final String label;
  final IconData? icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: icon != null ? Icon(icon) : null,
      title: Text(label),
      selected: selected,
      onTap: onTap,
    );
  }
}

class _DiscoveredTile extends ConsumerWidget {
  const _DiscoveredTile({required this.device});

  final DiscoveredDevice device;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Card(
      child: ListTile(
        leading: Icon(iconForDeviceKind(device.kind)),
        title: Text(device.name),
        subtitle: Text('${device.kind.label} · RSSI ${device.rssi}'),
        trailing: FilledButton(
          onPressed: () =>
              ref.read(bleHubRepositoryProvider).connect(device),
          child: const Text('Collega'),
        ),
      ),
    );
  }
}
