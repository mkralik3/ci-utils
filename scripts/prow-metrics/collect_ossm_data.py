#!/usr/bin/env python3
"""
OSSM Prow CI Data Collection Script

This script collects completed Prow CI executions plus all currently pending jobs for OpenShift
Service Mesh repositories from the OpenShift Prow API and generates comprehensive metrics and analysis.

Collection modes:
- Default: Last 100 completed executions + all pending jobs
- By count: Specific number dsdof completed jobs (--count N)
- By days: Historical data for specific time period (--days N)
- Interactive: Ask user for preference (--interactive)

Output: TSV file with columns:
Job_Name, Repository, Branch, Job_Type, Start_Time, Completion_Time,
Duration_Minutes, Status, Build_ID, Cluster, Test_Suite_Type, Spyglass_URL
"""

import urllib.request
import urllib.parse
import json
import csv
import re
import ssl
import argparse
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import statistics
import sys
import os

# OSSM Repositories to track
OSSM_REPOS = [
    'openshift-service-mesh/istio',
    'openshift-service-mesh/proxy',
    'openshift-service-mesh/sail-operator',
    'openshift-service-mesh/ztunnel'
]

class ProwJobAnalyzer:
    def __init__(self, collection_mode='count', count=100, days=None):
        self.prow_url = "https://prow.ci.openshift.org/prowjobs.js"
        self.jobs_data = []
        self.collection_mode = collection_mode  # 'count' or 'days'
        self.count = count  # number of completed jobs to collect
        self.days = days  # number of days of historical data

    def fetch_prow_data(self) -> List[Dict]:
        """Fetch and parse Prow jobs data"""
        print("Fetching Prow data from OpenShift API...")

        try:
            # Create SSL context that doesn't verify certificates
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            # Fetch data with urllib
            request = urllib.request.Request(self.prow_url)
            with urllib.request.urlopen(request, context=ssl_context, timeout=60) as response:
                content = response.read().decode('utf-8')

            # The response is directly a JSON object, not JavaScript code
            try:
                data = json.loads(content)
                if isinstance(data, dict) and 'items' in data:
                    jobs = data['items']
                elif isinstance(data, list):
                    jobs = data
                else:
                    raise Exception("Unexpected response format")
            except json.JSONDecodeError:
                # Fallback: try to parse as JavaScript variable
                markers_to_try = [
                    ("var allBuilds = ", ";\nvar spyglass"),
                    ("var allBuilds = ", ";\n"),
                    ("allBuilds = ", ";\n"),
                    ("var prowJobs = ", ";\n"),
                    ("prowJobs = ", ";\n")
                ]

                json_data = None
                for start_marker, end_marker in markers_to_try:
                    start_idx = content.find(start_marker)
                    if start_idx != -1:
                        start_idx += len(start_marker)
                        end_idx = content.find(end_marker, start_idx)
                        if end_idx != -1:
                            json_data = content[start_idx:end_idx].strip()
                            print(f"Found data with marker: {start_marker}")
                            break

                if json_data is None:
                    print(f"Response preview: {content[:500]}")
                    raise Exception("Could not find prowJobs data in response")

                jobs = json.loads(json_data)
            print(f"Successfully parsed {len(jobs)} total Prow jobs")

            return jobs

        except Exception as e:
            print(f"Error fetching Prow data: {e}")
            return []

    def filter_ossm_jobs(self, jobs: List[Dict]) -> List[Dict]:
        """Filter jobs for OSSM repositories based on collection mode"""
        ossm_jobs = []

        for job in jobs:
            try:
                # Check if this is an OSSM job
                job_spec = job.get('spec', {})
                refs = job_spec.get('refs', {})
                extra_refs = job_spec.get('extra_refs', [])

                # Check main refs
                repo_found = False
                if refs:
                    org = refs.get('org', '')
                    repo = refs.get('repo', '')
                    full_repo = f"{org}/{repo}"
                    if full_repo in OSSM_REPOS:
                        repo_found = True

                # Check extra refs
                if not repo_found:
                    for extra_ref in extra_refs:
                        org = extra_ref.get('org', '')
                        repo = extra_ref.get('repo', '')
                        full_repo = f"{org}/{repo}"
                        if full_repo in OSSM_REPOS:
                            repo_found = True
                            break

                if repo_found:
                    ossm_jobs.append(job)

            except Exception as e:
                continue

        print(f"Found {len(ossm_jobs)} OSSM jobs")

        # Sort by start time (most recent first)
        sorted_jobs = sorted(ossm_jobs, key=lambda x: x.get('status', {}).get('startTime', ''), reverse=True)

        # Separate completed and pending jobs
        completed_jobs = []
        pending_jobs = []

        # Calculate cutoff date if using days mode
        cutoff_date = None
        if self.collection_mode == 'days' and self.days:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.days)

        for job in sorted_jobs:
            status = job.get('status', {}).get('state', 'unknown')
            start_time = job.get('status', {}).get('startTime', '')

            # Filter by date if in days mode
            if cutoff_date and start_time:
                try:
                    job_date = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    if job_date < cutoff_date:
                        continue  # Skip jobs older than cutoff
                except Exception:
                    continue

            if status in ['pending', 'triggered']:
                pending_jobs.append(job)
            elif status in ['success', 'failure', 'aborted', 'error']:
                completed_jobs.append(job)

        # Select completed jobs based on collection mode
        if self.collection_mode == 'count':
            selected_completed = completed_jobs[:self.count]
            collection_desc = f"last {self.count} completed jobs"
        else:  # days mode
            selected_completed = completed_jobs
            collection_desc = f"completed jobs from last {self.days} days"

        # Combine with all pending jobs
        final_jobs = selected_completed + pending_jobs

        print(f"Selected {len(selected_completed)} completed jobs ({collection_desc}) + {len(pending_jobs)} pending jobs = {len(final_jobs)} total")
        return final_jobs

    def extract_job_info(self, job: Dict) -> Dict[str, Any]:
        """Extract relevant information from a Prow job"""
        try:
            spec = job.get('spec', {})
            status = job.get('status', {})
            metadata = job.get('metadata', {})

            # Extract repository info
            refs = spec.get('refs', {})
            repo_org = refs.get('org', '')
            repo_name = refs.get('repo', '')
            repository = f"{repo_org}/{repo_name}" if repo_org and repo_name else "unknown"

            # If main refs don't have OSSM repo, check extra_refs
            if repository not in OSSM_REPOS:
                extra_refs = spec.get('extra_refs', [])
                for extra_ref in extra_refs:
                    org = extra_ref.get('org', '')
                    repo = extra_ref.get('repo', '')
                    full_repo = f"{org}/{repo}"
                    if full_repo in OSSM_REPOS:
                        repository = full_repo
                        break

            # Extract job name - use the actual job name from spec
            job_name = spec.get('job', 'unknown')

            # Extract branch
            branch = refs.get('base_ref', 'unknown')

            # Extract job type
            job_type = spec.get('type', 'unknown')

            # Extract timing info
            start_time = status.get('startTime', '')
            completion_time = status.get('completionTime', '')

            # Calculate duration
            duration_minutes = 0
            if start_time and completion_time:
                try:
                    start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    end_dt = datetime.fromisoformat(completion_time.replace('Z', '+00:00'))
                    duration_minutes = (end_dt - start_dt).total_seconds() / 60
                except Exception:
                    duration_minutes = 0

            # Extract status
            job_status = status.get('state', 'unknown')

            # Extract build ID (use name from metadata, fallback to generated ID)
            build_id = metadata.get('name', '').split('-')[-1] if metadata.get('name') else 'unknown'

            # Extract cluster info from decoration config or job spec
            cluster = 'unknown'
            decoration_config = spec.get('decoration_config', {})
            if decoration_config:
                gcs_config = decoration_config.get('gcs_configuration', {})
                bucket = gcs_config.get('bucket', '')
                if 'test-platform-results' in bucket:
                    # Try to extract cluster from job name patterns
                    if 'build01' in str(job) or any('build01' in str(v) for v in job.values() if isinstance(v, str)):
                        cluster = 'build01'
                    elif 'build03' in str(job) or any('build03' in str(v) for v in job.values() if isinstance(v, str)):
                        cluster = 'build03'
                    elif 'build05' in str(job) or any('build05' in str(v) for v in job.values() if isinstance(v, str)):
                        cluster = 'build05'
                    elif 'build06' in str(job) or any('build06' in str(v) for v in job.values() if isinstance(v, str)):
                        cluster = 'build06'
                    elif 'build08' in str(job) or any('build08' in str(v) for v in job.values() if isinstance(v, str)):
                        cluster = 'build08'
                    elif 'build09' in str(job) or any('build09' in str(v) for v in job.values() if isinstance(v, str)):
                        cluster = 'build09'
                    elif 'build11' in str(job) or any('build11' in str(v) for v in job.values() if isinstance(v, str)):
                        cluster = 'build11'
                    else:
                        # Extract from URL pattern if available
                        url = status.get('url', '')
                        cluster_match = re.search(r'build(\d+)', url)
                        if cluster_match:
                            cluster = f"build{cluster_match.group(1)}"

            # Determine test suite type from job name
            test_suite_type = self.categorize_test_type(job_name)

            # Generate Spyglass URL
            spyglass_url = status.get('url', '')
            if not spyglass_url and build_id != 'unknown':
                # Construct URL based on job type and name
                if job_type == 'presubmit':
                    spyglass_url = f"https://prow.ci.openshift.org/view/gs/test-platform-results/pr-logs/{job_name}/{build_id}"
                else:
                    spyglass_url = f"https://prow.ci.openshift.org/view/gs/test-platform-results/logs/{job_name}/{build_id}"

            return {
                'Job_Name': job_name,
                'Repository': repository.split('/')[-1] if '/' in repository else repository,
                'Branch': branch,
                'Job_Type': job_type,
                'Start_Time': start_time,
                'Completion_Time': completion_time,
                'Duration_Minutes': round(duration_minutes, 2),
                'Status': job_status,
                'Build_ID': build_id,
                'Cluster': cluster,
                'Test_Suite_Type': test_suite_type,
                'Spyglass_URL': spyglass_url
            }

        except Exception as e:
            print(f"Error extracting job info: {e}")
            return None

    def categorize_test_type(self, job_name: str) -> str:
        """Categorize test type based on job name"""
        job_lower = job_name.lower()

        if 'sync-upstream' in job_lower:
            return 'sync-upstream'
        elif 'lpinterop' in job_lower or 'interop' in job_lower:
            return 'lpinterop'
        elif 'perfscale' in job_lower:
            return 'perfscale'
        elif 'integ' in job_lower and 'ambient' in job_lower:
            return 'integ-ambient'
        elif 'e2e' in job_lower:
            return 'e2e'
        elif 'unit' in job_lower:
            return 'unit'
        elif 'lint' in job_lower:
            return 'lint'
        elif 'gencheck' in job_lower:
            return 'gencheck'
        elif 'integration' in job_lower:
            return 'integration'
        else:
            return 'other'

    def save_tsv(self, jobs_info: List[Dict], filename: str = None):
        """Save job data to TSV file"""
        if not jobs_info:
            print("No job data to save")
            return

        # Generate descriptive filename if not provided
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            completed_jobs = len([j for j in jobs_info if j['Status'] not in ['pending', 'triggered']])
            pending_jobs = len([j for j in jobs_info if j['Status'] in ['pending', 'triggered']])

            if self.collection_mode == 'count':
                filename = f'ossm_prow_last_{self.count}_completed_plus_{pending_jobs}_pending_{timestamp}.tsv'
            else:
                filename = f'ossm_prow_{self.days}_days_completed_{completed_jobs}_plus_{pending_jobs}_pending_{timestamp}.tsv'

        with open(filename, 'w', newline='', encoding='utf-8') as tsvfile:
            fieldnames = [
                'Job_Name', 'Repository', 'Branch', 'Job_Type',
                'Start_Time', 'Completion_Time', 'Duration_Minutes',
                'Status', 'Build_ID', 'Cluster', 'Test_Suite_Type', 'Spyglass_URL'
            ]

            writer = csv.DictWriter(tsvfile, fieldnames=fieldnames, delimiter='\t')
            writer.writeheader()
            writer.writerows(jobs_info)

        self.saved_filename = filename
        print(f"TSV file saved: {filename}")

    def generate_report(self, jobs_info: List[Dict]) -> str:
        """Generate formatted report"""
        if not jobs_info:
            return "No OSSM jobs found in the data."

        # Calculate statistics
        total_jobs = len(jobs_info)
        successful_jobs = len([j for j in jobs_info if j['Status'] == 'success'])
        failed_jobs = len([j for j in jobs_info if j['Status'] == 'failure'])
        aborted_jobs = len([j for j in jobs_info if j['Status'] == 'aborted'])
        pending_jobs = len([j for j in jobs_info if j['Status'] in ['pending', 'triggered']])
        completed_jobs = successful_jobs + failed_jobs + aborted_jobs

        # Calculate rates based on completed jobs only (excluding pending)
        success_rate = (successful_jobs / completed_jobs * 100) if completed_jobs > 0 else 0
        failure_rate = (failed_jobs / completed_jobs * 100) if completed_jobs > 0 else 0
        aborted_rate = (aborted_jobs / completed_jobs * 100) if completed_jobs > 0 else 0
        pending_rate = (pending_jobs / total_jobs * 100) if total_jobs > 0 else 0

        # Repository breakdown
        repo_counts = {}
        for job in jobs_info:
            repo = job['Repository']
            repo_counts[repo] = repo_counts.get(repo, 0) + 1

        # Job type analysis
        type_stats = {}
        for job in jobs_info:
            test_type = job['Test_Suite_Type']
            if test_type not in type_stats:
                type_stats[test_type] = {
                    'count': 0,
                    'durations': [],
                    'success': 0,
                    'failure': 0
                }
            type_stats[test_type]['count'] += 1
            type_stats[test_type]['durations'].append(job['Duration_Minutes'])
            if job['Status'] == 'success':
                type_stats[test_type]['success'] += 1
            elif job['Status'] == 'failure':
                type_stats[test_type]['failure'] += 1

        # Calculate medians
        for test_type in type_stats:
            durations = type_stats[test_type]['durations']
            if durations:
                type_stats[test_type]['median'] = statistics.median(durations)
                type_stats[test_type]['min'] = min(durations)
                type_stats[test_type]['max'] = max(durations)

        # Build cluster usage
        cluster_counts = {}
        for job in jobs_info:
            cluster = job['Cluster']
            cluster_counts[cluster] = cluster_counts.get(cluster, 0) + 1

        # Time distribution
        time_buckets = {'00:00-06:00': 0, '06:00-12:00': 0, '12:00-18:00': 0, '18:00-24:00': 0}
        for job in jobs_info:
            start_time = job['Start_Time']
            if start_time:
                try:
                    hour = datetime.fromisoformat(start_time.replace('Z', '+00:00')).hour
                    if 0 <= hour < 6:
                        time_buckets['00:00-06:00'] += 1
                    elif 6 <= hour < 12:
                        time_buckets['06:00-12:00'] += 1
                    elif 12 <= hour < 18:
                        time_buckets['12:00-18:00'] += 1
                    else:
                        time_buckets['18:00-24:00'] += 1
                except:
                    continue

        # Date range
        dates = []
        for job in jobs_info:
            if job['Start_Time']:
                try:
                    date = datetime.fromisoformat(job['Start_Time'].replace('Z', '+00:00'))
                    dates.append(date)
                except:
                    continue

        if dates:
            start_date = min(dates).strftime('%B %d, %Y')
            end_date = max(dates).strftime('%B %d, %Y')
        else:
            start_date = end_date = "Unknown"

        # Failed jobs
        failed_job_list = [j for j in jobs_info if j['Status'] == 'failure']

        # Generate report
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        # Generate title based on collection mode
        completed_jobs = len([j for j in jobs_info if j['Status'] not in ['pending', 'triggered']])
        if self.collection_mode == 'count':
            title = f"PROW CI EXECUTION DATA - LAST {self.count} COMPLETED + PENDING JOBS"
        else:
            title = f"PROW CI EXECUTION DATA - {self.days} DAYS HISTORICAL + PENDING JOBS"

        separator = "=" * len(title)

        report = f"""{title}
{separator}
Data collected: {current_time}
Time range: {start_date} to {end_date}

## SUMMARY STATISTICS

**Total executions:** {total_jobs} ({completed_jobs} completed + {pending_jobs} pending)
**Date range:** {start_date} to {end_date}
**Success rate:** {success_rate:.1f}% ({successful_jobs} successful out of {completed_jobs} completed)
**Failure rate:** {failure_rate:.1f}% ({failed_jobs} failed out of {completed_jobs} completed)
**Aborted rate:** {aborted_rate:.1f}% ({aborted_jobs} aborted out of {completed_jobs} completed)
**Pending jobs:** {pending_jobs} currently running

**Repository breakdown:**
"""

        for repo, count in sorted(repo_counts.items()):
            percentage = (count / total_jobs * 100) if total_jobs > 0 else 0
            report += f"- {repo}: {count} jobs ({percentage:.1f}%)\n"

        report += """
## EXECUTION TIME BY JOB TYPE

**Median execution times:**
| Job Type | Median Duration | Count | Range |
|----------|----------------|--------|--------|
"""

        for test_type, stats in sorted(type_stats.items()):
            median = stats.get('median', 0)
            count = stats['count']
            min_dur = stats.get('min', 0)
            max_dur = stats.get('max', 0)
            report += f"| {test_type} | {median:.1f} min | {count} | {min_dur:.1f}-{max_dur:.1f} min |\n"

        # Longest running jobs
        longest_jobs = sorted(jobs_info, key=lambda x: x['Duration_Minutes'], reverse=True)[:3]
        report += """
**Longest running jobs:**
| Job Name | Duration | Status | Repository |
|----------|----------|--------|------------|
"""

        for job in longest_jobs:
            report += f"| {job['Job_Name']} | {job['Duration_Minutes']:.1f} min | {job['Status']} | {job['Repository']} |\n"

        report += """
## INFRASTRUCTURE USAGE

**Build clusters used:**
"""

        for cluster, count in sorted(cluster_counts.items()):
            percentage = (count / total_jobs * 100) if total_jobs > 0 else 0
            report += f"- {cluster}: {count} jobs ({percentage:.1f}%)\n"

        report += """
**Job distribution by time (UTC):**
"""

        for time_range, count in time_buckets.items():
            percentage = (count / total_jobs * 100) if total_jobs > 0 else 0
            report += f"- {time_range}: {count} jobs ({percentage:.1f}%)\n"

        report += """
## CURRENT ISSUES

**Failed jobs in dataset:**
| Job Name | Repository | Duration | Error Type |
|----------|------------|----------|------------|
"""

        for job in failed_job_list:
            report += f"| {job['Job_Name']} | {job['Repository']} | {job['Duration_Minutes']:.1f} min | failure |\n"

        if not failed_job_list:
            report += "No failed jobs in dataset.\n"

        report += """
**Currently pending jobs:**
| Job Name | Repository | Running Time | Status |
|----------|------------|--------------|--------|
"""

        pending_job_list = [j for j in jobs_info if j['Status'] in ['pending', 'triggered']]
        for job in pending_job_list:
            report += f"| {job['Job_Name']} | {job['Repository']} | {job['Duration_Minutes']:.1f} min | {job['Status']} |\n"

        if not pending_job_list:
            report += "No pending jobs in dataset.\n"

        # Add filename to report (will be updated when TSV is saved)
        report += f"""
## EXCEL DATA EXPORT

**TSV file saved to:** `{getattr(self, 'saved_filename', 'ossm_prow_data.tsv')}`

Columns: Job_Name, Repository, Branch, Job_Type, Start_Time, Completion_Time, Duration_Minutes, Status, Build_ID, Cluster, Test_Suite_Type, Spyglass_URL

The file can be directly imported into Excel/Google Sheets for further analysis.
"""

        return report

    def run(self):
        """Main execution method"""
        print("Starting OSSM Prow CI data collection...")
        print(f"Target repositories: {', '.join(OSSM_REPOS)}")

        if self.collection_mode == 'count':
            print(f"Target: {self.count} most recent completed jobs + all pending jobs")
        else:
            print(f"Target: completed jobs from last {self.days} days + all pending jobs")

        # Fetch data
        all_jobs = self.fetch_prow_data()
        if not all_jobs:
            print("Failed to fetch Prow data")
            return

        # Filter OSSM jobs
        ossm_jobs = self.filter_ossm_jobs(all_jobs)
        if not ossm_jobs:
            print("No OSSM jobs found in the data")
            return

        # Extract job information
        jobs_info = []
        for job in ossm_jobs:
            job_info = self.extract_job_info(job)
            if job_info:
                jobs_info.append(job_info)

        if not jobs_info:
            print("Failed to extract job information")
            return

        print(f"Processed {len(jobs_info)} OSSM jobs")

        # Save TSV file
        self.save_tsv(jobs_info)

        # Generate and print report
        report = self.generate_report(jobs_info)
        print("\n" + report)

def get_user_preference():
    """Interactive mode to get user preferences"""
    print("\nOSSM Prow CI Data Collection Options:")
    print("1. Default: Last 100 completed jobs + all pending")
    print("2. Custom count: Specify number of completed jobs")
    print("3. Time-based: Historical data for specific days")

    while True:
        try:
            choice = input("\nSelect option (1-3) [1]: ").strip()
            if not choice:
                choice = "1"

            if choice == "1":
                return 'count', 100, None
            elif choice == "2":
                count = int(input("Enter number of completed jobs to collect [100]: ") or "100")
                return 'count', count, None
            elif choice == "3":
                days = int(input("Enter number of days of historical data [7]: ") or "7")
                return 'days', None, days
            else:
                print("Invalid choice. Please select 1, 2, or 3.")
        except ValueError:
            print("Invalid input. Please enter a valid number.")
        except KeyboardInterrupt:
            print("\nOperation cancelled.")
            sys.exit(0)

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Collect OSSM Prow CI execution data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 collect_ossm_data.py                    # Default: 100 completed + pending
  python3 collect_ossm_data.py --interactive      # Ask user for preferences
  python3 collect_ossm_data.py --count 200        # 200 completed + pending
  python3 collect_ossm_data.py --days 7           # Last 7 days + pending
        """
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument('--count', type=int, metavar='N',
                       help='Number of completed jobs to collect (default: 100)')
    group.add_argument('--days', type=int, metavar='N',
                       help='Number of days of historical data to collect')
    group.add_argument('--interactive', action='store_true',
                       help='Interactive mode: ask user for preferences')

    return parser.parse_args()

if __name__ == "__main__":
    args = parse_arguments()

    # Determine collection parameters
    if args.interactive:
        collection_mode, count, days = get_user_preference()
    elif args.days:
        collection_mode, count, days = 'days', None, args.days
    elif args.count:
        collection_mode, count, days = 'count', args.count, None
    else:
        # Default: 100 completed jobs
        collection_mode, count, days = 'count', 100, None

    analyzer = ProwJobAnalyzer(collection_mode=collection_mode, count=count, days=days)
    analyzer.run()