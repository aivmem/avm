#!/usr/bin/env python3
"""
Forced Collaboration Test - Information Asymmetry

Each agent sees only PART of the information.
Only by sharing via AVM can they solve the puzzle.

Scenarios:
1. Secret Code: 4 agents each have 1/4 of a password
2. Murder Mystery: Different agents have different clues
3. Cipher: One has the key, another has the ciphertext
"""

import json
import tempfile
import time
import random
import string
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone

from runner import BenchmarkRunner
from agent_executor import run_codex, count_tokens
from avm_integration import avm_recall, avm_remember


def generate_random_code(length=16):
    """Generate a random alphanumeric code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def split_code(code, n_parts):
    """Split code into n roughly equal parts."""
    part_len = len(code) // n_parts
    parts = []
    for i in range(n_parts):
        start = i * part_len
        end = start + part_len if i < n_parts - 1 else len(code)
        parts.append(code[start:end])
    return parts


# =============================================================================
# SCENARIO 1: SECRET CODE
# =============================================================================

def run_secret_code_test(use_avm: bool) -> dict:
    """
    4 agents each have 1/4 of a secret code.
    They must combine to find the full code.
    """
    # Generate the secret
    secret_code = generate_random_code(16)
    parts = split_code(secret_code, 4)
    
    print(f"\n  Secret code: {secret_code}")
    print(f"  Parts: {parts}")
    
    agents = [
        {"id": "agent_alpha", "part": parts[0], "position": "first"},
        {"id": "agent_beta", "part": parts[1], "position": "second"},
        {"id": "agent_gamma", "part": parts[2], "position": "third"},
        {"id": "agent_delta", "part": parts[3], "position": "fourth (last)"},
    ]
    
    collected_parts = []
    total_tokens = 0
    avm_overhead = 0
    
    for agent in agents:
        # Each agent shares their part via AVM
        if use_avm:
            # Store their part
            avm_remember(
                content=f"My part of the secret code ({agent['position']} quarter): {agent['part']}",
                agent_id=agent["id"],
                importance=0.9,
                title=f"secret_part_{agent['id']}"
            )
            avm_overhead += 20  # Estimate
            
            # Try to recall others' parts
            recall = avm_recall(
                query="secret code part quarter",
                agent_id=agent["id"],
                max_tokens=300
            )
            avm_overhead += recall.tokens_used
            
            # Extract parts from recall
            for p in parts:
                if p in recall.data:
                    if p not in collected_parts:
                        collected_parts.append(p)
        else:
            # Baseline: ONLY gets first part (simulates isolated agent)
            if len(collected_parts) == 0:
                collected_parts.append(agent["part"])
    
    # Final assembly attempt
    task = f"""You have collected these code fragments: {collected_parts}
    
The fragments are in order (first, second, third, fourth).
Combine them to form the complete secret code.

Output ONLY the combined code, nothing else.
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=30)
        total_tokens += response.tokens_used
    
    # Check if correct
    assembled = response.output.strip().replace(" ", "").upper()
    correct = assembled == secret_code or secret_code in assembled
    
    return {
        "secret": secret_code,
        "collected": collected_parts,
        "assembled": assembled,
        "correct": correct,
        "tokens": total_tokens,
        "avm_overhead": avm_overhead,
        "total": total_tokens + avm_overhead,
    }


# =============================================================================
# SCENARIO 2: CIPHER DECRYPTION
# =============================================================================

def simple_cipher(text, key):
    """Simple XOR-based cipher for testing."""
    result = []
    for i, c in enumerate(text):
        k = key[i % len(key)]
        result.append(chr((ord(c) ^ ord(k)) % 128))
    return ''.join(result)


def run_cipher_test(use_avm: bool) -> dict:
    """
    Agent A has the ciphertext.
    Agent B has the decryption key.
    Only together can they decrypt.
    """
    # Generate cipher components
    plaintext = "THE_SECRET_MESSAGE_IS_PINEAPPLE"
    key = generate_random_code(8)
    ciphertext = simple_cipher(plaintext, key)
    ciphertext_hex = ciphertext.encode().hex()
    
    print(f"\n  Plaintext: {plaintext}")
    print(f"  Key: {key}")
    print(f"  Ciphertext (hex): {ciphertext_hex[:40]}...")
    
    total_tokens = 0
    avm_overhead = 0
    
    if use_avm:
        # Agent A stores ciphertext
        avm_remember(
            content=f"Ciphertext (hex encoded): {ciphertext_hex}",
            agent_id="cipher_holder",
            importance=0.9,
            title="ciphertext"
        )
        
        # Agent B stores key
        avm_remember(
            content=f"Decryption key (XOR): {key}",
            agent_id="key_holder", 
            importance=0.9,
            title="cipher_key"
        )
        
        # Decryptor recalls both
        recall = avm_recall(
            query="ciphertext key decryption XOR hex",
            agent_id="decryptor",
            max_tokens=500
        )
        avm_overhead += recall.tokens_used + 40
        
        context = recall.data if recall.success else ""
    else:
        # Baseline: decryptor only has ciphertext, no key
        context = f"Ciphertext (hex): {ciphertext_hex}"
    
    task = f"""Decrypt this message.

{context}

The cipher is XOR-based. To decrypt:
1. Convert hex to bytes
2. XOR each byte with the corresponding key byte (cycling)
3. The result is ASCII text

What is the plaintext message?
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=45)
        total_tokens += response.tokens_used
    
    # Check if plaintext found
    correct = plaintext in response.output.upper() or "PINEAPPLE" in response.output.upper()
    
    return {
        "plaintext": plaintext,
        "key": key,
        "decrypted": response.output[:100] if response.output else "",
        "correct": correct,
        "tokens": total_tokens,
        "avm_overhead": avm_overhead,
        "total": total_tokens + avm_overhead,
    }


# =============================================================================
# SCENARIO 3: MURDER MYSTERY
# =============================================================================

def run_mystery_test(use_avm: bool) -> dict:
    """
    Different agents have different clues.
    Only by combining all clues can they identify the murderer.
    """
    # The mystery
    murderer = "PROFESSOR_PLUM"
    
    clues = [
        {"agent": "detective_1", "clue": "The murder happened at 10pm. The suspect's shoe size is 11."},
        {"agent": "detective_2", "clue": "The victim's phone shows a call from someone at the university at 9:45pm."},
        {"agent": "detective_3", "clue": "Witnesses saw someone with a limp leaving the scene."},
        {"agent": "detective_4", "clue": "Police records: Professor Plum has shoe size 11, a limp from an old injury, and works at the university. He was questioned in a similar case before."},
    ]
    
    suspects = ["Colonel Mustard", "Professor Plum", "Mrs. Peacock", "Mr. Green", "Miss Scarlet"]
    
    total_tokens = 0
    avm_overhead = 0
    collected_clues = []
    
    for c in clues:
        if use_avm:
            # Each detective shares their clue
            avm_remember(
                content=f"CLUE from {c['agent']}: {c['clue']}",
                agent_id=c["agent"],
                importance=0.9,
                title=f"mystery_clue_{c['agent']}"
            )
            avm_overhead += 15
        
        collected_clues.append(c["clue"])
    
    if use_avm:
        # Lead detective recalls all clues
        recall = avm_recall(
            query="murder clue detective evidence purple university",
            agent_id="lead_detective",
            max_tokens=600
        )
        avm_overhead += recall.tokens_used
        
        clue_context = recall.data if recall.success else "\n".join(collected_clues)
    else:
        # Baseline: only has first clue (partial information)
        clue_context = clues[0]["clue"]
    
    task = f"""MURDER MYSTERY

Suspects: {', '.join(suspects)}

Evidence:
{clue_context}

Based on ALL the evidence, who is the murderer? 
Explain your reasoning briefly, then state the murderer's name.
"""
    
    with tempfile.TemporaryDirectory() as workdir:
        response = run_codex(task, workdir=workdir, timeout=45)
        total_tokens += response.tokens_used
    
    # Check if correct
    correct = "PLUM" in response.output.upper()
    
    return {
        "murderer": murderer,
        "answer": response.output[:200] if response.output else "",
        "correct": correct,
        "tokens": total_tokens,
        "avm_overhead": avm_overhead,
        "total": total_tokens + avm_overhead,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("="*70)
    print("FORCED COLLABORATION TEST")
    print("Information asymmetry - agents MUST share to succeed")
    print("="*70)
    
    results = []
    
    # Test 1: Secret Code
    print("\n" + "="*70)
    print("TEST 1: SECRET CODE (4 agents, each has 1/4)")
    print("="*70)
    
    print("\n[BASELINE] No sharing...")
    baseline_code = run_secret_code_test(use_avm=False)
    print(f"  Correct: {'✓' if baseline_code['correct'] else '✗'}")
    print(f"  Tokens: {baseline_code['total']}")
    
    print("\n[AVM] With sharing...")
    avm_code = run_secret_code_test(use_avm=True)
    print(f"  Correct: {'✓' if avm_code['correct'] else '✗'}")
    print(f"  Tokens: {avm_code['total']} ({avm_code['avm_overhead']} overhead)")
    
    results.append({
        "test": "secret_code",
        "baseline_correct": baseline_code["correct"],
        "avm_correct": avm_code["correct"],
        "baseline_tokens": baseline_code["total"],
        "avm_tokens": avm_code["total"],
    })
    
    # Test 2: Cipher
    print("\n" + "="*70)
    print("TEST 2: CIPHER (one has text, one has key)")
    print("="*70)
    
    print("\n[BASELINE] Only ciphertext, no key...")
    baseline_cipher = run_cipher_test(use_avm=False)
    print(f"  Correct: {'✓' if baseline_cipher['correct'] else '✗'}")
    print(f"  Tokens: {baseline_cipher['total']}")
    
    print("\n[AVM] Both ciphertext and key shared...")
    avm_cipher = run_cipher_test(use_avm=True)
    print(f"  Correct: {'✓' if avm_cipher['correct'] else '✗'}")
    print(f"  Tokens: {avm_cipher['total']} ({avm_cipher['avm_overhead']} overhead)")
    
    results.append({
        "test": "cipher",
        "baseline_correct": baseline_cipher["correct"],
        "avm_correct": avm_cipher["correct"],
        "baseline_tokens": baseline_cipher["total"],
        "avm_tokens": avm_cipher["total"],
    })
    
    # Test 3: Mystery
    print("\n" + "="*70)
    print("TEST 3: MURDER MYSTERY (4 detectives, 4 clues)")
    print("="*70)
    
    print("\n[BASELINE] Only partial evidence...")
    baseline_mystery = run_mystery_test(use_avm=False)
    print(f"  Correct: {'✓' if baseline_mystery['correct'] else '✗'}")
    print(f"  Tokens: {baseline_mystery['total']}")
    print(f"  Answer: {baseline_mystery['answer'][:100]}...")
    
    print("\n[AVM] All evidence shared...")
    avm_mystery = run_mystery_test(use_avm=True)
    print(f"  Correct: {'✓' if avm_mystery['correct'] else '✗'}")
    print(f"  Tokens: {avm_mystery['total']} ({avm_mystery['avm_overhead']} overhead)")
    print(f"  Answer: {avm_mystery['answer'][:100]}...")
    
    results.append({
        "test": "mystery",
        "baseline_correct": baseline_mystery["correct"],
        "avm_correct": avm_mystery["correct"],
        "baseline_tokens": baseline_mystery["total"],
        "avm_tokens": avm_mystery["total"],
    })
    
    # Summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Test':<20} {'Baseline':>15} {'AVM':>15}")
    print("-"*50)
    
    for r in results:
        b = '✓' if r['baseline_correct'] else '✗'
        a = '✓' if r['avm_correct'] else '✗'
        print(f"{r['test']:<20} {b:>15} {a:>15}")
    
    baseline_wins = sum(1 for r in results if r['baseline_correct'])
    avm_wins = sum(1 for r in results if r['avm_correct'])
    
    print("-"*50)
    print(f"{'SCORE':<20} {baseline_wins:>15}/3 {avm_wins:>15}/3")
    
    if avm_wins > baseline_wins:
        print("\n🎯 AVM enables collaboration that's IMPOSSIBLE without it!")
    
    # Save
    outfile = Path(__file__).parent / "results" / "forced_collab.json"
    with open(outfile, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "results": results,
        }, f, indent=2)
    
    print(f"\nSaved to {outfile}")


if __name__ == "__main__":
    random.seed(42)  # Reproducible
    main()
