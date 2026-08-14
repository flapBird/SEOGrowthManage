# Remote Agent Integration Guide

## Overview

The remote agent integration allows SEO Growth Console to automatically batch and send keyword candidates to a remote Claude Code Agent for intelligent judgment. This enables automated keyword discovery with minimal API cost optimization through local filtering and batch processing.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   SEO Console   │    │   File Queue    │    │  Claude Agent   │
│                 │    │                 │    │                 │
│ - Filter locally│───▶│ - in/pending/   │───▶│ - Process batch │
│ - Batch worthy  │    │ - out/done/     │◀───│ - Return results│
│ - Monitor queue │    │ - JSON files    │    │ - Judge keywords│
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Prerequisites

1. **Host machine with cron service**
2. **File permissions** for the `data/agent_queue` directory
3. **Environment variables** configured in `.env`

## Setup

### 1. Enable Agent Integration

Add to your `.env` file:
```env
# Enable agent integration
agent_integration_enabled=true

# Agent configuration
agent_batch_size=20
agent_dispatch_interval_seconds=1800  # 30 minutes
agent_collect_interval_seconds=300    # 5 minutes
agent_review_cooldown_hours=72
agent_min_score=20.0
agent_queue_dir=agent_queue
```

### 2. Create Queue Directory

```bash
mkdir -p data/agent_queue/in/pending
mkdir -p data/agent_queue/in/processed  
mkdir -p data/agent_queue/out/done
mkdir -p data/agent_queue/out/archived
```

Ensure proper permissions:
```bash
chmod 755 data/agent_queue
chmod 755 data/agent_queue/in
chmod 755 data/agent_queue/out
```

### 3. Set up Cron Jobs

On your host machine, add these cron jobs:

```bash
# Dispatch candidates to agent (every 30 minutes)
*/30 * * * * cd /path/to/SEOGrowthManage && python -c "
import asyncio
import sys
sys.path.append('/path/to/SEOGrowthManage')
from app.keyword_discovery.agent_queue import dispatch_due_to_agent
asyncio.run(dispatch_due_to_agent())
"

# Collect agent results (every 5 minutes)
*/5 * * * * cd /path/to/SEOGrowthManage && python -c "
import asyncio
import sys
sys.path.append('/path/to/SEOGrowthManage')
from app.keyword_discovery.agent_queue import collect_agent_results
asyncio.run(collect_agent_results())
"
```

## Agent Processing Flow

### 1. Local Filtering

Before sending candidates to the remote agent, the system performs local filtering:

- **Length filter**: Keywords shorter than 3 characters
- **Number/word filter**: Pure numbers or symbols
- **Cooldown filter**: Recently judged or ignored candidates
- **Score filter**: Candidates below minimum score threshold

### 2. Batching

Worthy candidates are batched into JSON files:

```json
{
  "batch_id": "20240814-143022-a1b2c3d",
  "created_at": "2024-08-14T14:30:22",
  "candidates": [
    {
      "candidate_id": 123,
      "keyword": "seo optimization",
      "language": "en",
      "country": "us",
      "source_count": 5,
      "scores": {
        "total": 45,
        "heat": 30,
        "freshness": 40,
        "intent": 35,
        "competition": 50,
        "confidence": 60
      }
    }
  ]
}
```

### 3. Remote Processing

The remote agent should:

1. Monitor `data/agent_queue/in/pending/` for new JSON files
2. Process each batch and return results
3. Write results to `data/agent_queue/out/done/`

### 4. Result Collection

The console automatically:

- Monitors `out/done/` for result files
- Updates candidate records with agent judgments
- Archives processed files
- Sends notifications for new "hot" keywords

## Agent Script Example

Here's an example script to process agent batches:

```python
#!/usr/bin/env python3
import json
import os
from pathlib import Path
import httpx
from datetime import datetime

def process_agent_batch():
    """Process pending agent batches and return results."""
    queue_dir = Path("data/agent_queue")
    pending_dir = queue_dir / "in" / "pending"
    done_dir = queue_dir / "out" / "done"
    
    for batch_file in pending_dir.glob("*.json"):
        try:
            # Read batch
            with open(batch_file, 'r', encoding='utf-8') as f:
                batch = json.load(f)
            
            results = []
            for candidate in batch['candidates']:
                # Process with Claude or other AI
                result = judge_keyword(candidate)
                results.append(result)
            
            # Write results
            result_file = done_dir / f"{batch_file.stem}_results.json"
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "batch_id": batch["batch_id"],
                    "processed_at": datetime.now().isoformat(),
                    "results": results
                }, f, ensure_ascii=False, indent=2)
            
            # Archive input file
            archive_dir = queue_dir / "in" / "processed"
            archive_dir.mkdir(exist_ok=True)
            batch_file.rename(archive_dir / batch_file.name)
            
        except Exception as e:
            print(f"Error processing {batch_file}: {e}")

def judge_keyword(candidate):
    """Judge a single keyword candidate."""
    keyword = candidate["keyword"]
    scores = candidate["scores"]
    
    # Implement your judgment logic here
    # This could use Claude API, other LLMs, or custom rules
    
    if scores["total"] > 40 and scores["heat"] > 30:
        return {
            "candidate_id": candidate["candidate_id"],
            "keyword": keyword,
            "verdict": "hot",
            "kd": estimate_kd(keyword),
            "reason": "High score and trending",
            "judged_at": datetime.now().isoformat()
        }
    else:
        return {
            "candidate_id": candidate["candidate_id"],
            "keyword": keyword,
            "verdict": "cold",
            "kd": None,
            "reason": "Score below threshold",
            "judged_at": datetime.now().isoformat()
        }

def estimate_kd(keyword):
    """Estimated keyword difficulty."""
    # Implement your KD estimation logic
    return 35

if __name__ == "__main__":
    process_agent_batch()
```

## Monitoring

### Web Interface

Access the agent dashboard at `/agent` to monitor:

- Queue statistics
- Batch history
- Manual dispatch/collect triggers
- Individual batch details

### Logs

Monitor application logs for agent-related events:

```bash
# Check recent agent activity
grep -i "agent" logs/app.log

# Monitor queue files
ls -la data/agent_queue/in/pending/
ls -la data/agent_queue/out/done/
```

### Notification Integration

Configure notification channels to receive alerts for:

- New "hot" keywords discovered by agent
- Processing errors
- Queue status updates

## Troubleshooting

### Common Issues

1. **Queue files not being processed**
   - Check cron jobs are running
   - Verify file permissions
   - Check disk space

2. **Agent results not being collected**
   - Verify agent script is running
   - Check output file format
   - Monitor for file permission errors

3. **High API costs**
   - Adjust `agent_batch_size` and intervals
   - Fine-tune `agent_min_score`
   - Monitor review cooldown settings

### Debug Commands

```bash
# Test manual dispatch
python -c "
import asyncio
from app.keyword_discovery.agent_queue import dispatch_due_to_agent
asyncio.run(dispatch_due_to_agent())
"

# Test manual collection  
python -c "
import asyncio
from app.keyword_discovery.agent_queue import collect_agent_results
asyncio.run(collect_agent_results())
"

# Check queue directory structure
find data/agent_queue -type f -exec ls -la {} \;
```

## Performance Optimization

1. **Batch Size**: Adjust based on API costs vs. processing efficiency
2. **Intervals**: Balance between real-time processing and cost control
3. **Local Filtering**: Fine-tune thresholds to minimize unnecessary API calls
4. **Cooldown Periods**: Prevent duplicate processing of unchanged keywords

## Security Considerations

- Queue files contain keyword data, ensure proper access controls
- Archive processed files for audit trail
- Monitor for unusual processing patterns
- Use encrypted connections for remote agent communication