import os
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import matplotlib.pyplot as plt

from utils.logger import get_logger

logger = get_logger(__name__)


class Reporter:
    """Generates reports and dashboards for LCA filing results."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize reporter.

        Args:
            config: Reporter configuration
        """
        self.config = config
        self.results_dir = config.get("results_dir", "data/results")

        # Create results directory if it doesn't exist
        os.makedirs(self.results_dir, exist_ok=True)

    def save_results(self, results: List[Dict[str, Any]]) -> str:
        """
        Save results to a JSON file.

        Args:
            results: List of filing results

        Returns:
            Path to the saved file
        """
        timestamp = int(time.time())
        filename = f"{self.results_dir}/lca_results_{timestamp}.json"

        try:
            with open(filename, "w") as f:
                json.dump(results, f, indent=2)

            logger.info(f"Results saved to {filename}")
            return filename

        except Exception as e:
            logger.error(f"Error saving results: {str(e)}")
            return ""

    def generate_dashboard(self, results: List[Dict[str, Any]], output_path: Optional[str] = None) -> str:
        """
        Generate an HTML dashboard of LCA filing results.

        Args:
            results: List of filing results
            output_path: Path to save the HTML dashboard

        Returns:
            Path to the generated dashboard
        """
        if not results:
            logger.warning("No results to generate dashboard")
            return ""

        if output_path is None:
            timestamp = int(time.time())
            output_path = f"{self.results_dir}/lca_dashboard_{timestamp}.html"

        try:
            # Convert results to DataFrame
            df = pd.DataFrame(results)

            # Calculate success rate
            success_count = sum(1 for r in results if r.get("status") == "success")
            total_count = len(results)
            success_rate = (success_count / total_count) * 100 if total_count > 0 else 0

            # Calculate average processing time
            if "processing_time" in df.columns:
                avg_time = df["processing_time"].mean()
            else:
                avg_time = 0

            # Generate HTML
            html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>LCA Filing Dashboard</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 20px; }}
                    .dashboard {{ max-width: 1200px; margin: 0 auto; }}
                    .summary {{ display: flex; justify-content: space-between; margin-bottom: 20px; }}
                    .summary-card {{ background-color: #f8f9fa; border-radius: 5px; padding: 15px; width: 30%; }}
                    .success {{ color: green; }}
                    .error {{ color: red; }}
                    table {{ width: 100%; border-collapse: collapse; }}
                    th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
                    th {{ background-color: #f2f2f2; }}
                    tr:hover {{ background-color: #f5f5f5; }}
                </style>
            </head>
            <body>
                <div class="dashboard">
                    <h1>LCA Filing Dashboard</h1>
                    <div class="summary">
                        <div class="summary-card">
                            <h3>Success Rate</h3>
                            <p><span class="success">{success_rate:.1f}%</span> ({success_count}/{total_count})</p>
                        </div>
                        <div class="summary-card">
                            <h3>Average Processing Time</h3>
                            <p>{avg_time:.1f} seconds</p>
                        </div>
                        <div class="summary-card">
                            <h3>Last Updated</h3>
                            <p>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        </div>
                    </div>

                    <h2>Filing Results</h2>
                    <table>
                        <tr>
                            <th>ID</th>
                            <th>Status</th>
                            <th>Confirmation #</th>
                            <th>Time</th>
                            <th>Timestamp</th>
                        </tr>
            """

            # Add rows for each result
            for result in results:
                status_class = "success" if result.get("status") == "success" else "error"
                html += f"""
                    <tr>
                        <td>{result.get("application_id", "N/A")}</td>
                        <td class="{status_class}">{result.get("status", "N/A")}</td>
                        <td>{result.get("confirmation_number", "N/A")}</td>
                        <td>{result.get("processing_time", 0):.1f}s</td>
                        <td>{result.get("timestamp", "N/A")}</td>
                    </tr>
                """

            html += """
                    </table>
                </div>
            </body>
            </html>
            """

            # Write to file
            with open(output_path, "w") as f:
                f.write(html)

            logger.info(f"Dashboard exported to {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Error generating dashboard: {str(e)}")
            return ""

    def generate_statistics(self, results: List[Dict[str, Any]], output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate statistics and charts for LCA filing results.

        Args:
            results: List of filing results
            output_dir: Directory to save charts

        Returns:
            Dictionary with statistics
        """
        if not results:
            logger.warning("No results to generate statistics")
            return {}

        if output_dir is None:
            output_dir = f"{self.results_dir}/stats_{int(time.time())}"

        os.makedirs(output_dir, exist_ok=True)

        try:
            # Convert results to DataFrame
            df = pd.DataFrame(results)

            # Basic statistics
            stats = {
                "total_applications": len(results),
                "success_count": sum(1 for r in results if r.get("status") == "success"),
                "error_count": sum(1 for r in results if r.get("status") == "error"),
                "average_processing_time": df["processing_time"].mean() if "processing_time" in df.columns else 0
            }

            stats["success_rate"] = (stats["success_count"] / stats["total_applications"]) * 100 if stats[
                                                                                                        "total_applications"] > 0 else 0

            # Status distribution chart
            if "status" in df.columns:
                status_counts = df["status"].value_counts()
                plt.figure(figsize=(10, 6))
                status_counts.plot(kind="bar",
                                   color=["green" if s == "success" else "red" for s in status_counts.index])
                plt.title("LCA Filing Status Distribution")
                plt.xlabel("Status")
                plt.ylabel("Count")
                plt.tight_layout()
                plt.savefig(f"{output_dir}/status_distribution.png")

                stats["status_distribution"] = status_counts.to_dict()

            # Processing time histogram
            if "processing_time" in df.columns:
                plt.figure(figsize=(10, 6))
                plt.hist(df["processing_time"], bins=20, color="blue", alpha=0.7)
                plt.title("LCA Filing Processing Time Distribution")
                plt.xlabel("Processing Time (seconds)")
                plt.ylabel("Count")
                plt.tight_layout()
                plt.savefig(f"{output_dir}/processing_time_distribution.png")

                stats["processing_time_stats"] = {
                    "min": df["processing_time"].min(),
                    "max": df["processing_time"].max(),
                    "mean": df["processing_time"].mean(),
                    "median": df["processing_time"].median(),
                    "std": df["processing_time"].std()
                }

            # Write statistics to JSON file
            with open(f"{output_dir}/statistics.json", "w") as f:
                json.dump(stats, f, indent=2)

            logger.info(f"Statistics saved to {output_dir}")
            return stats

        except Exception as e:
            logger.error(f"Error generating statistics: {str(e)}")
            return {}

