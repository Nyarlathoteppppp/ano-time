#!/usr/bin/env python3
"""
Test script for FunASR integration
Tests if FunASR can be imported and initialized
"""

import numpy as np
import sys

def test_funasr_import():
    """Test if FunASR can be imported"""
    print("=" * 60)
    print("TEST 1: Testing FunASR Import")
    print("=" * 60)
    try:
        from funasr import AutoModel
        print("✓ FunASR imported successfully")
        return True
    except ImportError as e:
        print(f"✗ FunASR import failed: {e}")
        print("\nTo install FunASR, run:")
        print("  pip install funasr modelscope")
        return False

def test_transcriber_backends():
    """Test Transcriber with different backends"""
    print("\n" + "=" * 60)
    print("TEST 2: Testing Transcriber Backend Support")
    print("=" * 60)
    
    from transcriber import Transcriber
    
    backends_to_test = [
        ("whisper", "base"),
        ("funasr", "paraformer-zh"),
    ]
    
    results = []
    
    for backend, model in backends_to_test:
        print(f"\nTesting backend: {backend} with model: {model}")
        try:
            transcriber = Transcriber(
                backend=backend,
                model_size=model,
                device="cpu",
                compute_type="int8"
            )
            print(f"✓ {backend} backend initialized successfully")
            print(f"  - Backend type: {transcriber.backend}")
            print(f"  - Model: {transcriber.model_size}")
            results.append((backend, True))
        except Exception as e:
            print(f"✗ {backend} backend failed: {e}")
            results.append((backend, False))
    
    return results

def test_funasr_transcription():
    """Test actual FunASR transcription with dummy audio"""
    print("\n" + "=" * 60)
    print("TEST 3: Testing FunASR Transcription (Warmup)")
    print("=" * 60)
    
    try:
        from transcriber import Transcriber
        
        print("Initializing FunASR transcriber...")
        transcriber = Transcriber(
            backend="funasr",
            model_size="paraformer-zh",
            device="cpu",
            compute_type="int8"
        )
        
        # Create 1 second of silence (16kHz)
        print("Creating test audio (1 second of silence)...")
        dummy_audio = np.zeros(16000, dtype=np.float32)
        
        print("Running transcription...")
        result = transcriber.transcribe(dummy_audio)
        
        print(f"✓ Transcription completed")
        print(f"  - Result: '{result}' (empty is expected for silence)")
        return True
        
    except Exception as e:
        print(f"✗ Transcription test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("FunASR Integration Test Suite")
    print("=" * 60 + "\n")
    
    # Test 1: Import
    import_ok = test_funasr_import()
    
    if not import_ok:
        print("\n" + "=" * 60)
        print("SKIPPING REMAINING TESTS - FunASR not installed")
        print("=" * 60)
        sys.exit(1)
    
    # Test 2: Backend initialization
    backend_results = test_transcriber_backends()
    
    # Test 3: Transcription (only if FunASR backend initialized)
    funasr_ok = any(backend == "funasr" and ok for backend, ok in backend_results)
    
    if funasr_ok:
        transcription_ok = test_funasr_transcription()
    else:
        print("\n" + "=" * 60)
        print("SKIPPING TEST 3 - FunASR backend not available")
        print("=" * 60)
        transcription_ok = False
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Import Test:         {'✓ PASSED' if import_ok else '✗ FAILED'}")
    
    for backend, ok in backend_results:
        print(f"{backend.capitalize()} Backend:      {'✓ PASSED' if ok else '✗ FAILED'}")
    
    if funasr_ok:
        print(f"Transcription Test:  {'✓ PASSED' if transcription_ok else '✗ FAILED'}")
    
    print("=" * 60)
    
    # Exit code
    all_ok = import_ok and all(ok for _, ok in backend_results) and (transcription_ok if funasr_ok else True)
    
    if all_ok:
        print("\n✓ ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n✗ SOME TESTS FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
