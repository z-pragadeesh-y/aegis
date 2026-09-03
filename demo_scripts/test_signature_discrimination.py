import os
import sys
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import numpy as np
from memory_engine.memory import embed_text

def run_discrimination_test():
    sig_a = "Description: Critical memory leak on checkout service | Root Cause: Memory leak in worker process | Metrics: status=degraded, cpu=94.5%, error_rate=0.18"
    sig_b = "Description: Network partition affecting payment gateway connectivity | Root Cause: Network split-brain between payment gateway and database cluster | Metrics: status=degraded, cpu=91.0%, error_rate=0.16"

    vec_a = np.array(embed_text(sig_a))
    vec_b = np.array(embed_text(sig_b))

    dot = np.dot(vec_a, vec_b)
    norm = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    cosine_sim = dot / norm

    print("=========================================================================")
    print("STEP 2 — FAULT-SIGNATURE SIMILARITY DISCRIMINATION TEST")
    print("=========================================================================")
    print(f"Signature A: {sig_a}")
    print(f"Signature B: {sig_b}")
    print(f"Exact Numeric Cosine Similarity Score: {cosine_sim:.6f}")
    print("=========================================================================")

if __name__ == "__main__":
    run_discrimination_test()
