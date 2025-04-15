# utils/reporting.py
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
    """Generates reports and dashboards for LCA filing results with generation ID support."""

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

    def save_results(self, results: List[Dict[str, Any]], output_path: Optional[str] = None) -> str:
        """
        Save results to a JSON file.

        Args:
            results: List of filing results
            output_path: Optional specific path for output file

        Returns:
            Path to the saved file
        """
        if output_path:
            filename = output_path
            # Ensure directory exists
            os.makedirs(os.path.dirname(filename), exist_ok=True)
        else:
            # Use generation ID if available in the first result
            if results and "generation_id" in results[0]:
                generation_id = results[0]["generation_id"]
                gen_dir = f"{self.results_dir}/{generation_id}"
                os.makedirs(gen_dir, exist_ok=True)
                filename = f"{gen_dir}/lca_results.json"
            else:
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

        if output_path:
            # Use provided path
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
        else:
            # Use generation ID if available in the first result
            if "generation_id" in results[0]:
                generation_id = results[0]["generation_id"]
                gen_dir = f"{self.results_dir}/{generation_id}"
                os.makedirs(gen_dir, exist_ok=True)
                output_path = f"{gen_dir}/lca_dashboard.html"
            else:
                timestamp = int(time.time())
                output_path = f"{self.results_dir}/lca_dashboard_{timestamp}.html"

        try:
            # Get generation ID for display
            generation_id = results[0].get("generation_id", "Unknown") if results else "Unknown"

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
                    .header {{ margin-bottom: 20px; }}
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
                    <div class="header">
                        <h1>LCA Filing Dashboard</h1>
                        <p><strong>Generation ID:</strong> {generation_id}</p>
                    </div>

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
                            <th>Steps Completed</th>
                            <th>Timestamp</th>
                        </tr>
            """

            # Add rows for each result
            for result in results:
                status_class = "success" if result.get("status") == "success" else "error"
                # Format steps completed to be more readable
                steps = result.get("steps_completed", [])
                steps_text = ", ".join(step.replace("_", " ").capitalize() for step in steps)

                html += f"""
                    <tr>
                        <td>{result.get("application_id", "N/A")}</td>
                        <td class="{status_class}">{result.get("status", "N/A")}</td>
                        <td>{result.get("confirmation_number", "N/A")}</td>
                        <td>{result.get("processing_time", 0):.1f}s</td>
                        <td>{steps_text}</td>
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

        if output_dir:
            # Use provided directory
            os.makedirs(output_dir, exist_ok=True)
        else:
            # Use generation ID if available in the first result
            if "generation_id" in results[0]:
                generation_id = results[0]["generation_id"]
                output_dir = f"{self.results_dir}/{generation_id}/stats"
            else:
                timestamp = int(time.time())
                output_dir = f"{self.results_dir}/stats_{timestamp}"

            os.makedirs(output_dir, exist_ok=True)

        try:
            # Convert results to DataFrame
            df = pd.DataFrame(results)

            # Basic statistics
            stats = {
                "generation_id": results[0].get("generation_id", "Unknown") if results else "Unknown",
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

            # Step completion analysis
            if "steps_completed" in df.columns:
                all_steps = set()
                for steps in df["steps_completed"]:
                    if isinstance(steps, list):
                        all_steps.update(steps)

                step_counts = {
                    step: sum(1 for steps in df["steps_completed"] if isinstance(steps, list) and step in steps)
                    for step in all_steps}

                if step_counts:
                    plt.figure(figsize=(12, 6))
                    steps = list(step_counts.keys())
                    counts = list(step_counts.values())

                    # Sort by process order (if steps follow a logical sequence)
                    if "navigation" in step_counts and "login" in step_counts:
                        # Define a logical order for steps
                        step_order = [
                            "navigation",
                            "login",
                            "new_lca_navigation",
                            "form_type_selection"
                        ]

                        # Add any section steps in order
                        section_steps = [s for s in steps if s.startswith("section_")]
                        step_order.extend(sorted(section_steps))

                        # Add submission step at the end
                        if "submission" in steps:
                            step_order.append("submission")

                        # Filter to only include steps that actually exist in our data
                        ordered_steps = [s for s in step_order if s in steps]

                        # Add any remaining steps that weren't in our predefined order
                        remaining_steps = [s for s in steps if s not in ordered_steps]
                        ordered_steps.extend(remaining_steps)

                        # Use the ordered steps
                        steps = ordered_steps
                        counts = [step_counts[s] for s in steps]

                    # Create the plot
                    plt.bar(steps, counts)
                    plt.title("Step Completion Analysis")
                    plt.xlabel("Step")
                    plt.ylabel("Number of Applications")
                    plt.xticks(rotation=45, ha="right")
                    plt.tight_layout()
                    plt.savefig(f"{output_dir}/step_completion.png")

                    stats["step_completion"] = step_counts

            # Write statistics to JSON file
            with open(f"{output_dir}/statistics.json", "w") as f:
                json.dump(stats, f, indent=2)

            logger.info(f"Statistics saved to {output_dir}")
            return stats

        except Exception as e:
            logger.error(f"Error generating statistics: {str(e)}")
            return {}

    def generate_summary_report(self, generation_id: str) -> Dict[str, Any]:
        """
        Generate a summary report for a specific generation ID.

        Args:
            generation_id: Generation ID to report on

        Returns:
            Dictionary with summary information
        """
        # Check if generation directory exists
        gen_dir = f"{self.results_dir}/{generation_id}"
        if not os.path.exists(gen_dir):
            logger.error(f"No data found for generation ID: {generation_id}")
            return {"error": "Generation ID not found"}

        try:
            # Look for results JSON file
            results_file = f"{gen_dir}/lca_results.json"
            if not os.path.exists(results_file):
                logger.error(f"No results file found for generation ID: {generation_id}")
                return {"error": "No results file found"}

            # Load results
            with open(results_file, "r") as f:
                results = json.load(f)

            # Get statistics
            stats_dir = f"{gen_dir}/stats"
            stats_file = f"{stats_dir}/statistics.json"

            if os.path.exists(stats_file):
                with open(stats_file, "r") as f:
                    stats = json.load(f)
            else:
                # Generate statistics if not already existing
                stats = self.generate_statistics(results, stats_dir)

            # Find screenshot directories
            screenshot_dir = f"screenshots/{generation_id}"
            if os.path.exists(screenshot_dir):
                # Count screenshots by application ID
                app_screenshots = {}
                for app_id in os.listdir(screenshot_dir):
                    app_dir = f"{screenshot_dir}/{app_id}"
                    if os.path.isdir(app_dir):
                        screenshot_count = len([f for f in os.listdir(app_dir) if f.endswith(".png")])
                        app_screenshots[app_id] = screenshot_count

                total_screenshots = sum(app_screenshots.values())
            else:
                app_screenshots = {}
                total_screenshots = 0

            # Build summary report
            summary = {
                "generation_id": generation_id,
                "timestamp": datetime.now().isoformat(),
                "applications": {
                    "total": len(results),
                    "success": stats.get("success_count", 0),
                    "error": stats.get("error_count", 0),
                    "success_rate": stats.get("success_rate", 0)
                },
                "performance": {
                    "average_processing_time": stats.get("average_processing_time", 0),
                    "total_screenshots": total_screenshots,
                    "screenshots_by_application": app_screenshots
                },
                "file_paths": {
                    "results_file": results_file,
                    "dashboard_file": f"{gen_dir}/lca_dashboard.html",
                    "statistics_directory": stats_dir,
                    "screenshots_directory": screenshot_dir
                }
            }

            # Write summary to file
            summary_file = f"{gen_dir}/summary.json"
            with open(summary_file, "w") as f:
                json.dump(summary, f, indent=2)

            logger.info(f"Summary report generated for generation ID: {generation_id}")
            return summary

        except Exception as e:
            logger.error(f"Error generating summary report: {str(e)}")
            return {"error": str(e)}