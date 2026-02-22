"""Benchmark suite for Artemis City memory operations."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import time
import statistics
from integration.memory_decay import MemoryDecayService, MemoryNode
from integration.hebbian_sync import HebbianSyncService, WeightUpdate
from agents.atp.atp_parser import ATPParser


class BenchmarkResults:
    """Container for benchmark results."""

    def __init__(self, name, latencies):
        self.name = name
        self.latencies = latencies

    def get_stats(self):
        """Calculate statistics for latencies."""
        return {
            'min_ms': min(self.latencies),
            'max_ms': max(self.latencies),
            'mean_ms': statistics.mean(self.latencies),
            'median_ms': statistics.median(self.latencies),
            'stdev_ms': statistics.stdev(self.latencies) if len(self.latencies) > 1 else 0,
            'count': len(self.latencies),
        }


def benchmark_memory_decay_cycle(iterations=100):
    """Benchmark memory decay cycle latency."""
    print("\nBenchmarking Memory Decay Cycle...")
    print("-" * 60)

    service = MemoryDecayService(decay_rate=0.1)
    latencies = []

    # Register nodes
    for i in range(50):
        node = MemoryNode(f"mem_{i}", f"content_{i}", 0.9)
        service.register_node(node)

    # Run decay cycles and measure latency
    for iteration in range(iterations):
        start_time = time.perf_counter()
        service.run_decay_cycle()
        end_time = time.perf_counter()

        latency_ms = (end_time - start_time) * 1000
        latencies.append(latency_ms)

    return BenchmarkResults("Memory Decay Cycle", latencies)


def benchmark_hebbian_sync_batch(iterations=100, batch_size=100):
    """Benchmark Hebbian sync batch processing latency."""
    print("\nBenchmarking Hebbian Sync Batch Processing...")
    print("-" * 60)

    service = HebbianSyncService()
    latencies = []

    for iteration in range(iterations):
        # Queue batch of updates
        for i in range(batch_size):
            update = WeightUpdate(
                f"w_{iteration}_{i}",
                0.5,
                0.5 + (i * 0.0001),
                i * 0.0001
            )
            service.queue_update(update)

        # Measure flush latency
        start_time = time.perf_counter()
        result = service.flush_batch()
        end_time = time.perf_counter()

        latency_ms = (end_time - start_time) * 1000
        latencies.append(latency_ms)

    return BenchmarkResults("Hebbian Sync Batch", latencies)


def benchmark_atp_parsing(iterations=10000):
    """Benchmark ATP parsing latency."""
    print("\nBenchmarking ATP Parse Latency...")
    print("-" * 60)

    parser = ATPParser()
    latencies = []

    atp_samples = [
        "premise: A. conclusion: B.",
        "premise: (A & B). conclusion: C.",
        "premise: (A | (B & C)). conclusion: D.",
        "premise: ~A. premise: B. conclusion: (C | D).",
    ]

    for iteration in range(iterations):
        atp = atp_samples[iteration % len(atp_samples)]

        start_time = time.perf_counter()
        result = parser.parse_with_metrics(atp)
        end_time = time.perf_counter()

        latency_ms = (end_time - start_time) * 1000
        latencies.append(latency_ms)

    return BenchmarkResults("ATP Parsing", latencies)


def print_results_table(results):
    """Print benchmark results in a formatted table."""
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS SUMMARY")
    print("=" * 80)

    header = f"{'Operation':<30} {'Min (ms)':<12} {'Max (ms)':<12} {'Mean (ms)':<12} {'Median (ms)':<12} {'StdDev':<12} {'Count':<8}"
    print(header)
    print("-" * 80)

    for result in results:
        stats = result.get_stats()
        row = (
            f"{result.name:<30} "
            f"{stats['min_ms']:<12.4f} "
            f"{stats['max_ms']:<12.4f} "
            f"{stats['mean_ms']:<12.4f} "
            f"{stats['median_ms']:<12.4f} "
            f"{stats['stdev_ms']:<12.4f} "
            f"{stats['count']:<8d}"
        )
        print(row)

    print("=" * 80)


def print_detailed_results(results):
    """Print detailed results for each benchmark."""
    print("\n" + "=" * 80)
    print("DETAILED BENCHMARK ANALYSIS")
    print("=" * 80)

    for result in results:
        stats = result.get_stats()
        print(f"\n{result.name}")
        print("-" * 80)
        print(f"  Minimum latency:     {stats['min_ms']:.4f} ms")
        print(f"  Maximum latency:     {stats['max_ms']:.4f} ms")
        print(f"  Mean latency:        {stats['mean_ms']:.4f} ms")
        print(f"  Median latency:      {stats['median_ms']:.4f} ms")
        print(f"  Std deviation:       {stats['stdev_ms']:.4f} ms")
        print(f"  Total iterations:    {stats['count']}")
        print(f"  Total time:          {sum(result.latencies):.4f} ms")
        print(f"  Throughput:          {stats['count'] / (sum(result.latencies) / 1000):.2f} ops/sec")


def main():
    """Run all benchmarks."""
    print("\n" + "=" * 80)
    print("ARTEMIS CITY BENCHMARK SUITE")
    print("=" * 80)

    results = []

    # Run benchmarks
    print("\nStarting benchmarks...")

    try:
        # Memory decay benchmark
        decay_result = benchmark_memory_decay_cycle(iterations=100)
        results.append(decay_result)
    except Exception as e:
        print(f"Error in memory decay benchmark: {e}")

    try:
        # Hebbian sync benchmark
        sync_result = benchmark_hebbian_sync_batch(iterations=100, batch_size=100)
        results.append(sync_result)
    except Exception as e:
        print(f"Error in Hebbian sync benchmark: {e}")

    try:
        # ATP parsing benchmark
        atp_result = benchmark_atp_parsing(iterations=10000)
        results.append(atp_result)
    except Exception as e:
        print(f"Error in ATP parsing benchmark: {e}")

    # Print results
    if results:
        print_results_table(results)
        print_detailed_results(results)

        print("\n" + "=" * 80)
        print("BENCHMARK COMPLETE")
        print("=" * 80)
    else:
        print("\nNo benchmarks completed successfully.")


if __name__ == "__main__":
    main()
