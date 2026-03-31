#!/usr/bin/env python3
"""
Vernis Integration Test Suite

Tests downloading, NFT management, carousels, and count consistency.

Usage:
  python3 test_vernis.py                    # Test against localhost
  python3 test_vernis.py --host 192.168.1.100    # Test against specific Pi
  python3 test_vernis.py --verbose          # Show detailed output
  python3 test_vernis.py --quick            # Skip slow tests
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output"""
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


class VernisTestSuite:
    """Comprehensive test suite for Vernis API"""

    def __init__(self, host="127.0.0.1", port=5000, verbose=False):
        self.base_url = f"http://{host}:{port}"
        self.verbose = verbose
        self.results = []
        self.test_carousel_name = f"_test_carousel_{int(time.time())}"

    def log(self, message, level="info"):
        """Log message with color"""
        if level == "pass":
            print(f"{Colors.GREEN}✓ PASS{Colors.RESET}: {message}")
        elif level == "fail":
            print(f"{Colors.RED}✗ FAIL{Colors.RESET}: {message}")
        elif level == "warn":
            print(f"{Colors.YELLOW}⚠ WARN{Colors.RESET}: {message}")
        elif level == "info":
            print(f"{Colors.BLUE}ℹ INFO{Colors.RESET}: {message}")
        elif level == "debug" and self.verbose:
            print(f"  DEBUG: {message}")

    def api_get(self, endpoint):
        """Make GET request to API"""
        url = f"{self.base_url}{endpoint}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}", "status_code": e.code}
        except urllib.error.URLError as e:
            return {"error": f"Connection failed: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def api_post(self, endpoint, data=None):
        """Make POST request to API"""
        url = f"{self.base_url}{endpoint}"
        try:
            json_data = json.dumps(data or {}).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=json_data,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode('utf-8'))
                body["status_code"] = e.code
                return body
            except:
                return {"error": f"HTTP {e.code}", "status_code": e.code}
        except urllib.error.URLError as e:
            return {"error": f"Connection failed: {e.reason}"}
        except Exception as e:
            return {"error": str(e)}

    def api_delete(self, endpoint):
        """Make DELETE request to API"""
        url = f"{self.base_url}{endpoint}"
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json"},
                method="DELETE"
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}", "status_code": e.code}
        except Exception as e:
            return {"error": str(e)}

    def record_result(self, test_name, passed, message="", details=None):
        """Record test result"""
        self.results.append({
            "test": test_name,
            "passed": passed,
            "message": message,
            "details": details,
            "timestamp": datetime.now().isoformat()
        })
        if passed:
            self.log(f"{test_name}: {message}", "pass")
        else:
            self.log(f"{test_name}: {message}", "fail")
        if details and self.verbose:
            self.log(f"Details: {details}", "debug")

    # ==================
    # Connection Tests
    # ==================

    def test_api_connection(self):
        """Test basic API connectivity"""
        result = self.api_get("/api/status")
        if "error" in result and "Connection" in str(result.get("error", "")):
            self.record_result("API Connection", False, f"Cannot connect to {self.base_url}")
            return False
        self.record_result("API Connection", True, f"Connected to {self.base_url}")
        return True

    # ==================
    # NFT Count Tests
    # ==================

    def test_pinned_art_count(self):
        """Test that pinned art count is correct"""
        result = self.api_get("/api/pinned-art")
        if "error" in result:
            self.record_result("Pinned Art Count", False, result.get("error"))
            return None

        count = len(result) if isinstance(result, list) else 0
        self.record_result("Pinned Art Count", True, f"Found {count} pinned artworks")
        return count

    def test_download_progress(self):
        """Test download progress endpoint returns valid data"""
        result = self.api_get("/api/download-progress")
        if "error" in result:
            self.record_result("Download Progress", False, result.get("error"))
            return None

        # Verify required fields
        required_fields = ["completed", "total", "failed", "active"]
        missing = [f for f in required_fields if f not in result]

        if missing:
            self.record_result("Download Progress", False, f"Missing fields: {missing}")
            return None

        active = result.get("active", False)
        completed = result.get("completed", 0)
        total = result.get("total", 0)
        failed = result.get("failed", 0)
        actual = result.get("actual_files", completed)

        status = "active" if active else "idle"
        self.record_result(
            "Download Progress",
            True,
            f"Status: {status}, Completed: {completed}/{total}, Failed: {failed}, Files: {actual}"
        )
        return result

    def test_nft_list_detailed(self):
        """Test detailed NFT list endpoint"""
        result = self.api_get("/api/nft-list-detailed")
        if "error" in result:
            self.record_result("NFT List Detailed", False, result.get("error"))
            return None

        nfts = result.get("nfts", [])
        self.record_result("NFT List Detailed", True, f"Found {len(nfts)} NFTs")
        return nfts

    # ==================
    # Carousel Tests
    # ==================

    def test_carousel_list(self):
        """Test listing carousels"""
        result = self.api_get("/api/carousels")
        if "error" in result:
            self.record_result("Carousel List", False, result.get("error"))
            return None

        carousels = result.get("carousels", [])
        self.record_result("Carousel List", True, f"Found {len(carousels)} carousels")
        return carousels

    def test_carousel_create(self):
        """Test creating a carousel"""
        data = {
            "name": self.test_carousel_name,
            "hidden": ["test_hidden_1.jpg", "test_hidden_2.png"]
        }
        result = self.api_post("/api/carousels", data)

        if "error" in result:
            self.record_result("Carousel Create", False, result.get("error"))
            return False

        if result.get("success"):
            self.record_result("Carousel Create", True, f"Created '{self.test_carousel_name}'")
            return True
        else:
            self.record_result("Carousel Create", False, "Unexpected response")
            return False

    def test_carousel_get(self):
        """Test getting a specific carousel"""
        result = self.api_get(f"/api/carousels/{self.test_carousel_name}")

        if "error" in result:
            self.record_result("Carousel Get", False, result.get("error"))
            return None

        hidden = result.get("hidden", [])
        self.record_result(
            "Carousel Get",
            True,
            f"Retrieved '{self.test_carousel_name}' with {len(hidden)} hidden items"
        )
        return result

    def test_carousel_delete(self):
        """Test deleting a carousel"""
        result = self.api_delete(f"/api/carousels/{self.test_carousel_name}")

        if "error" in result:
            self.record_result("Carousel Delete", False, result.get("error"))
            return False

        if result.get("success"):
            self.record_result("Carousel Delete", True, f"Deleted '{self.test_carousel_name}'")
            return True
        else:
            self.record_result("Carousel Delete", False, "Unexpected response")
            return False

    def test_carousel_count_after_delete(self):
        """Verify carousel count decreases after deletion"""
        # Get count before
        before = self.api_get("/api/carousels")
        before_count = len(before.get("carousels", []))

        # Create test carousel
        test_name = f"_count_test_{int(time.time())}"
        self.api_post("/api/carousels", {"name": test_name, "hidden": []})

        # Verify count increased
        after_create = self.api_get("/api/carousels")
        after_create_count = len(after_create.get("carousels", []))

        if after_create_count != before_count + 1:
            self.record_result(
                "Carousel Count (Create)",
                False,
                f"Expected {before_count + 1}, got {after_create_count}"
            )
            # Cleanup
            self.api_delete(f"/api/carousels/{test_name}")
            return False

        # Delete and verify count decreased
        self.api_delete(f"/api/carousels/{test_name}")
        after_delete = self.api_get("/api/carousels")
        after_delete_count = len(after_delete.get("carousels", []))

        if after_delete_count == before_count:
            self.record_result(
                "Carousel Count (Delete)",
                True,
                f"Count correctly updated: {before_count} → {after_create_count} → {after_delete_count}"
            )
            return True
        else:
            self.record_result(
                "Carousel Count (Delete)",
                False,
                f"Expected {before_count}, got {after_delete_count}"
            )
            return False

    # ==================
    # NFT Deletion Tests
    # ==================

    def test_nft_count_consistency(self):
        """
        Test that NFT counts are consistent across endpoints.
        Compares pinned-art count vs download-progress actual_files.
        """
        pinned = self.api_get("/api/pinned-art")
        progress = self.api_get("/api/download-progress")

        if "error" in pinned or "error" in progress:
            self.record_result(
                "NFT Count Consistency",
                False,
                "Could not fetch data from endpoints"
            )
            return False

        pinned_count = len(pinned) if isinstance(pinned, list) else 0
        progress_count = progress.get("actual_files", progress.get("completed", 0))

        # Allow for minor differences (external vs internal storage)
        if abs(pinned_count - progress_count) <= 2:
            self.record_result(
                "NFT Count Consistency",
                True,
                f"Counts match: pinned={pinned_count}, progress={progress_count}"
            )
            return True
        else:
            self.record_result(
                "NFT Count Consistency",
                False,
                f"Counts differ: pinned={pinned_count}, progress={progress_count}"
            )
            return False

    # ==================
    # Download History Tests
    # ==================

    def test_download_history(self):
        """Test download history endpoint"""
        result = self.api_get("/api/download-history")

        if "error" in result:
            self.record_result("Download History", False, result.get("error"))
            return None

        history = result.get("history", [])
        self.record_result("Download History", True, f"Found {len(history)} history entries")
        return history

    def test_download_status(self):
        """Test download status endpoint"""
        result = self.api_get("/api/download-status")

        if "error" in result:
            self.record_result("Download Status", False, result.get("error"))
            return None

        downloads = result.get("downloads", [])
        self.record_result("Download Status", True, f"Found {len(downloads)} download records")
        return downloads

    # ==================
    # Metadata Tests
    # ==================

    def test_nft_metadata_cache(self):
        """Test NFT metadata cache endpoint"""
        result = self.api_get("/api/nft-metadata")

        if "error" in result:
            self.record_result("NFT Metadata Cache", False, result.get("error"))
            return None

        nfts = result.get("nfts", {})
        collections = result.get("collections", [])
        artists = result.get("artists", [])

        self.record_result(
            "NFT Metadata Cache",
            True,
            f"Cached: {len(nfts)} NFTs, {len(collections)} collections, {len(artists)} artists"
        )
        return result

    # ==================
    # Settings Tests
    # ==================

    def test_ipfs_settings(self):
        """Test IPFS settings endpoint"""
        result = self.api_get("/api/ipfs/settings")

        if "error" in result:
            self.record_result("IPFS Settings", False, result.get("error"))
            return None

        timeout = result.get("download_timeout", 60)
        retries = result.get("download_retries", 3)

        self.record_result(
            "IPFS Settings",
            True,
            f"Timeout: {timeout}s, Retries: {retries}"
        )
        return result

    # ==================
    # Run All Tests
    # ==================

    def run_all(self, quick=False):
        """Run all tests"""
        print(f"\n{Colors.BOLD}{'=' * 50}{Colors.RESET}")
        print(f"{Colors.BOLD}Vernis Integration Test Suite{Colors.RESET}")
        print(f"{Colors.BOLD}{'=' * 50}{Colors.RESET}")
        print(f"Target: {self.base_url}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Mode: {'Quick' if quick else 'Full'}")
        print(f"{'=' * 50}\n")

        # Connection test first
        if not self.test_api_connection():
            print(f"\n{Colors.RED}Cannot connect to API. Aborting tests.{Colors.RESET}")
            return self.generate_report()

        print(f"\n{Colors.BOLD}--- NFT & Download Tests ---{Colors.RESET}")
        self.test_pinned_art_count()
        self.test_download_progress()
        self.test_nft_list_detailed()
        self.test_nft_count_consistency()
        self.test_download_history()
        self.test_download_status()

        print(f"\n{Colors.BOLD}--- Carousel Tests ---{Colors.RESET}")
        self.test_carousel_list()
        self.test_carousel_create()
        self.test_carousel_get()
        self.test_carousel_delete()
        if not quick:
            self.test_carousel_count_after_delete()

        print(f"\n{Colors.BOLD}--- Metadata & Settings Tests ---{Colors.RESET}")
        self.test_nft_metadata_cache()
        self.test_ipfs_settings()

        return self.generate_report()

    def generate_report(self):
        """Generate test report"""
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed

        print(f"\n{'=' * 50}")
        print(f"{Colors.BOLD}TEST SUMMARY{Colors.RESET}")
        print(f"{'=' * 50}")
        print(f"Total:  {total}")
        print(f"Passed: {Colors.GREEN}{passed}{Colors.RESET}")
        print(f"Failed: {Colors.RED}{failed}{Colors.RESET}")

        if failed > 0:
            print(f"\n{Colors.RED}Failed Tests:{Colors.RESET}")
            for r in self.results:
                if not r["passed"]:
                    print(f"  - {r['test']}: {r['message']}")

        success_rate = (passed / total * 100) if total > 0 else 0
        print(f"\nSuccess Rate: {success_rate:.1f}%")

        # Save report
        report = {
            "timestamp": datetime.now().isoformat(),
            "target": self.base_url,
            "total": total,
            "passed": passed,
            "failed": failed,
            "success_rate": success_rate,
            "results": self.results
        }

        return report

    def cleanup(self):
        """Clean up any test artifacts"""
        # Try to delete test carousel if it exists
        self.api_delete(f"/api/carousels/{self.test_carousel_name}")


def main():
    parser = argparse.ArgumentParser(description="Vernis Integration Test Suite")
    parser.add_argument("--host", default="127.0.0.1", help="Target host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Target port (default: 5000)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--quick", "-q", action="store_true", help="Skip slow tests")
    parser.add_argument("--output", "-o", help="Save report to JSON file")

    args = parser.parse_args()

    suite = VernisTestSuite(host=args.host, port=args.port, verbose=args.verbose)

    try:
        report = suite.run_all(quick=args.quick)

        if args.output:
            with open(args.output, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"\nReport saved to: {args.output}")

        # Notify API that tests are complete
        try:
            req = urllib.request.Request(
                f"{suite.base_url}/api/tests/complete",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=5)
        except:
            pass  # API might not be running or endpoint not available

        # Exit with error code if any tests failed
        sys.exit(0 if report["failed"] == 0 else 1)

    finally:
        suite.cleanup()


if __name__ == "__main__":
    main()
