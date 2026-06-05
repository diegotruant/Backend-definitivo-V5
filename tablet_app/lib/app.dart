import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:in_person_test_tablet/core/routing/app_router.dart';
import 'package:in_person_test_tablet/core/theme/app_theme.dart';

class InPersonTestApp extends ConsumerWidget {
  InPersonTestApp({super.key});

  final _router = createAppRouter();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp.router(
      title: 'Test in presenza',
      theme: AppTheme.light(),
      routerConfig: _router,
      debugShowCheckedModeBanner: false,
    );
  }
}
