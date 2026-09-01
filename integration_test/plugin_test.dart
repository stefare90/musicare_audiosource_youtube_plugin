import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:integration_test/integration_test.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:serious_python/serious_python.dart';

class TestTrack {
  final String name;
  final List<String> artists;
  final int durationMs;

  const TestTrack({
    required this.name,
    required this.artists,
    required this.durationMs,
  });

  Map<String, dynamic> toJson() => {
    'name': name,
    'artists': artists.map((a) => {'name': a}).toList(),
    'durationMs': durationMs,
  };
}

final List<TestTrack> realTestTracks = [
  const TestTrack(
    name: 'Come Together',
    artists: ['The Beatles'],
    durationMs: 259000, // 4:19
  ),
  const TestTrack(
    name: 'Bohemian Rhapsody',
    artists: ['Queen'],
    durationMs: 354000, // 5:54
  ),
];

Future<int> getUnusedPort() async {
  final socket = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
  final int port = socket.port;
  await socket.close();
  return port;
}

Future<void> waitForServerReady(
  int port, {
  Duration timeout = const Duration(seconds: 20),
}) async {
  final stopwatch = Stopwatch()..start();
  final client = http.Client();

  while (stopwatch.elapsed < timeout) {
    try {
      final response = await client.get(
        Uri.parse('http://127.0.0.1:$port/ping'),
      );
      if (response.statusCode == 200) {
        client.close();
        return;
      }
    } catch (_) {
      // Waiting for Python daemon to start
    }
    await Future.delayed(const Duration(milliseconds: 250));
  }

  client.close();
  throw TimeoutException(
    'Flask RPC server failed to start within ${timeout.inSeconds} seconds.',
  );
}

Future<void> verifyAudioStreamSource(Map<String, dynamic> stream) async {
  final url = stream['url'] as String?;
  expect(url, isNotNull);
  expect(url, startsWith('https://'));
  expect(url, contains('googlevideo.com'));

  final bitrate = stream['bitrate'] as num?;
  expect(bitrate, isNotNull);
  expect(bitrate, greaterThan(0));

  expect(stream['codec'], isNotNull);

  final expiresAt = stream['expiresAt'] as num?;
  expect(expiresAt, isNotNull);
  expect(expiresAt, greaterThan(DateTime.now().millisecondsSinceEpoch));

  final headers =
      (stream['headers'] as Map?)?.cast<String, String>() ?? <String, String>{};
  final requestHeaders = {...headers, 'Range': 'bytes=0-1024'};

  final client = http.Client();
  try {
    final response = await client.get(Uri.parse(url!), headers: requestHeaders);

    expect(
      [200, 206],
      contains(response.statusCode),
      reason:
          'Expected CDN response 200 or 206, but received HTTP ${response.statusCode}: ${response.reasonPhrase}',
    );

    final contentType = response.headers['content-type'] ?? '';
    expect(
      contentType,
      matches(RegExp(r'audio\/(mp4|webm|mpeg|opus)|video\/mp4')),
    );

    expect(response.bodyBytes.length, greaterThan(0));
    expect(response.bodyBytes.length, lessThanOrEqualTo(1025));
  } finally {
    client.close();
  }
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  HttpOverrides.global = null;

  group('YouTube Audio Source Plugin Integration Tests', () {
    const sourceZipPath = 'plugin.zip';
    late Directory pluginInstallDir;
    late int serverPort;
    late http.Client httpClient;

    setUpAll(() async {
      final sourceZipFile = File(sourceZipPath);
      expect(
        sourceZipFile.existsSync(),
        isTrue,
        reason: 'plugin.zip must exist. Run "python tool/build.py" first!',
      );

      final appSupportDir = await getApplicationSupportDirectory();
      pluginInstallDir = Directory(
        p.join(
          appSupportDir.path,
          'plugins',
          'org.musicare.audiosource.youtube',
        ),
      );

      if (pluginInstallDir.existsSync()) {
        pluginInstallDir.deleteSync(recursive: true);
      }
      pluginInstallDir.createSync(recursive: true);

      final zipBytes = sourceZipFile.readAsBytesSync();
      final archive = ZipDecoder().decodeBytes(zipBytes);

      for (final file in archive) {
        final filename = p.join(pluginInstallDir.path, file.name);
        if (file.isFile) {
          final outFile = File(filename);
          outFile.createSync(recursive: true);
          outFile.writeAsBytesSync(file.content as List<int>);
        } else {
          Directory(filename).createSync(recursive: true);
        }
      }

      httpClient = http.Client();
      serverPort = await getUnusedPort();

      final entryPointPath = p.join(pluginInstallDir.path, 'src', 'main.py');
      Directory.current = pluginInstallDir;

      SeriousPython.runProgram(
        entryPointPath,
        modulePaths: [pluginInstallDir.path],
        environmentVariables: {'PORT': serverPort.toString()},
        sync: false,
      );

      await waitForServerReady(serverPort);
    });

    tearDownAll(() {
      httpClient.close();
      SeriousPython.terminate();

      if (pluginInstallDir.existsSync()) {
        try {
          pluginInstallDir.deleteSync(recursive: true);
        } catch (_) {}
      }
    });

    testWidgets('Health check responds with valid plugin metadata', (
      tester,
    ) async {
      final response = await httpClient.get(
        Uri.parse('http://127.0.0.1:$serverPort/ping'),
      );
      expect(response.statusCode, equals(200));

      final Map<String, dynamic> data = jsonDecode(response.body);
      expect(data['status'], equals('ready'));
      expect(data['id'], equals('org.musicare.audiosource.youtube'));
      expect(data['name'], equals('MusicAre YouTube Audio Source'));
    });

    for (final track in realTestTracks) {
      testWidgets(
        'Resolves and validates playable audio stream for "${track.artists.first} - ${track.name}"',
        (tester) async {
          final uri = Uri.parse('http://127.0.0.1:$serverPort/get_stream');

          final response = await httpClient.post(
            uri,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'track': track.toJson(), 'quality': 'high'}),
          );

          expect(
            response.statusCode,
            equals(200),
            reason: 'Server returned error: ${response.body}',
          );

          final dynamic data = jsonDecode(response.body);
          expect(data, isA<List>());

          final List<dynamic> sources = data as List;
          expect(sources, isNotEmpty);

          final Map<String, dynamic> primaryStream = Map<String, dynamic>.from(
            sources.first as Map,
          );
          await verifyAudioStreamSource(primaryStream);
        },
      );
    }
  });
}
