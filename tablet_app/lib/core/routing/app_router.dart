import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:in_person_test_tablet/core/routing/routes.dart';
import 'package:in_person_test_tablet/presentation/screens/devices/devices_screen.dart';
import 'package:in_person_test_tablet/presentation/screens/home/home_screen.dart';

GoRouter createAppRouter() {
  return GoRouter(
    initialLocation: AppRoutes.home,
    routes: [
      GoRoute(
        path: AppRoutes.home,
        name: 'home',
        builder: (context, state) => const HomeScreen(),
      ),
      GoRoute(
        path: AppRoutes.devices,
        name: 'devices',
        builder: (context, state) => const DevicesScreen(),
      ),
    ],
    errorBuilder: (context, state) => Scaffold(
      body: Center(child: Text('Percorso non trovato: ${state.uri}')),
    ),
  );
}
