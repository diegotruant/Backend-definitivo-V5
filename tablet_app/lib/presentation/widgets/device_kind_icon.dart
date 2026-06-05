import 'package:flutter/material.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';

IconData iconForDeviceKind(DeviceKind kind) => switch (kind) {
      DeviceKind.roller => Icons.directions_bike,
      DeviceKind.heartRate => Icons.favorite,
      DeviceKind.coreTemperature => Icons.thermostat,
    };
