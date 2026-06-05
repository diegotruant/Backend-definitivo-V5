import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:in_person_test_tablet/core/config/app_config.dart';
import 'package:in_person_test_tablet/core/routing/routes.dart';
import 'package:in_person_test_tablet/domain/entities/test_type.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final useFake = AppConfig.current.useFakeBle;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Test in presenza'),
        actions: [
          if (useFake)
            Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Center(
                child: Chip(
                  label: Text(
                    'BLE simulato',
                    style: theme.textTheme.labelSmall,
                  ),
                  visualDensity: VisualDensity.compact,
                ),
              ),
            ),
        ],
      ),
      body: Row(
        children: [
          NavigationRail(
            selectedIndex: 0,
            onDestinationSelected: (i) {
              if (i == 1) context.go(AppRoutes.devices);
            },
            destinations: const [
              NavigationRailDestination(
                icon: Icon(Icons.science_outlined),
                selectedIcon: Icon(Icons.science),
                label: Text('Test'),
              ),
              NavigationRailDestination(
                icon: Icon(Icons.bluetooth_searching),
                selectedIcon: Icon(Icons.bluetooth_connected),
                label: Text('Dispositivi'),
              ),
            ],
          ),
          const VerticalDivider(width: 1),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.all(32),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Seleziona un protocollo',
                    style: theme.textTheme.headlineMedium,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Collega prima rullo e sensori dalla sezione Dispositivi.',
                    style: theme.textTheme.bodyLarge?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: 32),
                  Expanded(
                    child: GridView.count(
                      crossAxisCount: 2,
                      mainAxisSpacing: 16,
                      crossAxisSpacing: 16,
                      childAspectRatio: 2.4,
                      children: [
                        for (final t in InPersonTestType.values)
                          _TestTypeCard(
                            title: t.label,
                            subtitle: t.apiValue,
                            onTap: () {
                              ScaffoldMessenger.of(context).showSnackBar(
                                SnackBar(
                                  content: Text(
                                    'Protocollo "${t.label}" — prossimo step',
                                  ),
                                ),
                              );
                            },
                          ),
                      ],
                    ),
                  ),
                  FilledButton.icon(
                    onPressed: () => context.go(AppRoutes.devices),
                    icon: const Icon(Icons.bluetooth),
                    label: const Text('Gestisci dispositivi BLE'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TestTypeCard extends StatelessWidget {
  const _TestTypeCard({
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 4),
              Text(
                subtitle,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
