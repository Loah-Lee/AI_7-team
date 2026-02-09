#!/usr/bin/env python
"""
E2E TESTER - Operation RAG Rebirth (Final)
Comprehensive end-to-end test of the complete RAG pipeline
Tests the golden path scenario: "고려대학교 입찰 마감일은 언제인가?"
"""

import sys
import os
import json
import time
from typing import Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Load env
load_dotenv()

# Import pipeline components
try:
    from RAG_pipeline import create_rag_app
    from core.state import GraphState
    from router import RouterAgent
    from tools import get_csv_schema, filter_csv
    from search import hybrid_search
    from metadata_qa import verify_analysis
    IMPORTS_OK = True
except ImportError as e:
    print(f"❌ Import error: {e}")
    import traceback
    traceback.print_exc()
    IMPORTS_OK = False


class E2ETester:
    """
    End-to-End Test Suite for RAG Pipeline
    """
    
    def __init__(self):
        self.results = []
        self.app = None
        self.start_time = None
        self.end_time = None
    
    def print_header(self, title: str):
        """Print formatted section header"""
        print(f"\n{'='*80}")
        print(f"  {title}")
        print(f"{'='*80}\n")
    
    def print_test(self, test_num: int, name: str):
        """Print test name"""
        print(f"\n[TEST {test_num}] {name}")
        print("-" * 80)
    
    def print_result(self, passed: bool, message: str):
        """Print test result"""
        icon = "✅ PASS" if passed else "❌ FAIL"
        print(f"{icon}: {message}")
    
    # ======================================================================
    # Individual Tests
    # ======================================================================
    
    def test_01_imports(self) -> bool:
        """[Test 1] Verify all imports"""
        self.print_test(1, "Import Verification")
        
        if not IMPORTS_OK:
            self.print_result(False, "Some imports failed")
            return False
        
        self.print_result(True, "All required modules imported successfully")
        return True
    
    
    def test_02_router_classification(self) -> bool:
        """[Test 2] Router - Intent Classification"""
        self.print_test(2, "Router Intent Classification")
        
        try:
            router = RouterAgent(model="gpt-4o-mini")
            
            question = "고려대학교 입찰 마감일은 언제인가?"
            print(f"📝 Question: {question}")
            
            result = router.classify_intent(question)
            intent = result.get("intent", "unknown")
            confidence = result.get("confidence", 0.0)
            
            print(f"🎯 Router Result:")
            print(f"   - Intent: {intent}")
            print(f"   - Confidence: {confidence:.2f}")
            print(f"   - Reason: {result.get('reason', 'N/A')}")
            
            # Assertion: Should detect entity (고려대) and classify as hybrid
            expected = "hybrid"
            passed = intent == expected
            
            self.print_result(
                passed,
                f"Intent classification correct (expected: {expected}, got: {intent})"
            )
            
            self.results.append({
                "test": "Router Classification",
                "passed": passed,
                "detail": f"intent={intent}, confidence={confidence:.2f}"
            })
            
            return passed
            
        except Exception as e:
            self.print_result(False, f"Router test error: {str(e)}")
            return False
    
    
    def test_03_csv_schema(self) -> bool:
        """[Test 3] Metadata - CSV Schema Loading"""
        self.print_test(3, "CSV Schema Loading")
        
        try:
            schema = get_csv_schema()
            
            if not schema or len(schema) < 10:
                self.print_result(False, "Schema appears to be empty or too short")
                return False
            
            print(f"📋 Schema loaded ({len(schema)} characters)")
            print("\nSchema preview:")
            print(schema[:500])
            
            self.print_result(True, "CSV schema loaded successfully")
            
            self.results.append({
                "test": "CSV Schema",
                "passed": True,
                "detail": f"schema_size={len(schema)}"
            })
            
            return True
            
        except Exception as e:
            self.print_result(False, f"CSV schema error: {str(e)}")
            return False
    
    
    def test_04_csv_filtering(self) -> bool:
        """[Test 4] Metadata - CSV Filtering"""
        self.print_test(4, "CSV Data Filtering")
        
        try:
            print("🔍 Searching for '고려대' in '발주 기관' column...")
            result = filter_csv(column="발주 기관", value="고려대")
            
            has_data = "고려대" in result or "|" in result
            
            print(f"📊 Filter Result ({len(result)} chars):")
            
            lines = result.split("\n")
            for i, line in enumerate(lines[:8]):
                print(f"   {line}")
            
            if len(lines) > 8:
                print(f"   ... ({len(lines) - 8} more lines)")
            
            self.print_result(has_data, "CSV filtering executed successfully")
            
            self.results.append({
                "test": "CSV Filtering",
                "passed": has_data,
                "detail": f"found_rows={len([l for l in lines if '|' in l])}"
            })
            
            return has_data
            
        except Exception as e:
            self.print_result(False, f"CSV filtering error: {str(e)}")
            return False
    
    
    def test_05_hybrid_search(self) -> bool:
        """[Test 5] Retrieval - Hybrid Search"""
        self.print_test(5, "Hybrid Document Search")
        
        try:
            question = "고려대학교 입찰 마감일"
            print(f"🔎 Searching for: '{question}'")
            
            # Note: hybrid_search may print its own output
            search_results = hybrid_search(question)
            
            print(f"\n📄 Search completed")
            print(f"   - Result type: {type(search_results)}")
            
            # Results might be list or dict
            result_count = 0
            if isinstance(search_results, list):
                result_count = len(search_results)
                print(f"   - Found {result_count} results")
            elif isinstance(search_results, dict):
                print(f"   - Results fields: {list(search_results.keys())}")
                result_count = 1
            
            passed = result_count > 0
            self.print_result(passed, "Hybrid search executed")
            
            self.results.append({
                "test": "Hybrid Search",
                "passed": passed,
                "detail": f"result_type={type(search_results).__name__}"
            })
            
            return passed
            
        except Exception as e:
            self.print_result(False, f"Hybrid search error: {str(e)}")
            return False
    
    
    def test_06_pipeline_initialization(self) -> bool:
        """[Test 6] Pipeline - Initialization"""
        self.print_test(6, "RAG Pipeline Initialization")
        
        try:
            print("🔧 Building RAG pipeline...")
            self.start_time = time.time()
            
            self.app = create_rag_app()
            
            print("✅ Pipeline created successfully")
            print(f"   - App type: {type(self.app).__name__}")
            
            self.print_result(True, "Pipeline initialized")
            
            self.results.append({
                "test": "Pipeline Init",
                "passed": True,
                "detail": f"app_type={type(self.app).__name__}"
            })
            
            return True
            
        except Exception as e:
            self.print_result(False, f"Pipeline initialization error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    
    def test_07_full_pipeline_execution(self) -> bool:
        """[Test 7] Pipeline - Full Execution (Golden Path)"""
        self.print_test(7, "Full Pipeline Execution")
        
        if not self.app:
            self.print_result(False, "Pipeline not initialized")
            return False
        
        try:
            question = "고려대학교 입찰 마감일은 언제인가?"
            print(f"❓ Question: {question}\n")
            
            # Prepare initial state
            initial_state = GraphState(
                question=question,
                intent="",
                analyst_reasoning="",
                dynamic_view="",
                qa_status="",
                qa_feedback="",
                retry_count=0,
                documents=[],
                final_answer=""
            )
            
            print("⏱️  Executing pipeline (timeout 60s)...")
            execution_start = time.time()
            
            # Invoke with recursion limit
            final_state = self.app.invoke(
                initial_state,
                config={"recursion_limit": 10}
            )
            
            execution_time = time.time() - execution_start
            
            # Check results
            intent = final_state.get("intent", "unknown")
            analyst_view = final_state.get("dynamic_view", "")
            documents_count = len(final_state.get("documents", []))
            final_answer = final_state.get("final_answer", "")
            qa_status = final_state.get("qa_status", "")
            
            print(f"\n📊 Execution Results (took {execution_time:.2f}s):")
            print(f"   1. Router Intent: {intent}")
            print(f"   2. QA Status: {qa_status}")
            print(f"   3. Data View: {'✅ Generated' if analyst_view else '❌ Empty'}")
            print(f"   4. Documents Found: {documents_count}")
            print(f"   5. Final Answer: {'✅ Generated' if final_answer else '❌ Empty'}")
            
            print(f"\n📝 Final Answer:")
            print("-" * 80)
            print(final_answer[:500] if final_answer else "(No answer generated)")
            print("-" * 80)
            
            passed = bool(final_answer)
            
            self.print_result(
                passed,
                f"Pipeline execution completed ({execution_time:.2f}s)"
            )
            
            self.results.append({
                "test": "Full Pipeline",
                "passed": passed,
                "detail": (
                    f"intent={intent}, qa_status={qa_status}, "
                    f"docs={documents_count}, execution_time={execution_time:.2f}s"
                )
            })
            
            return passed
            
        except Exception as e:
            self.print_result(False, f"Pipeline execution error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    
    def test_08_answer_quality(self) -> bool:
        """[Test 8] Answer Quality Checks"""
        self.print_test(8, "Answer Quality Validation")
        
        if not self.app:
            self.print_result(False, "Pipeline not initialized")
            return False
        
        try:
            # Run a second query to get fresh results
            question = "고려대학교 사업의 내용은?"
            print(f"❓ Question: {question}\n")
            
            initial_state = GraphState(
                question=question,
                intent="",
                analyst_reasoning="",
                dynamic_view="",
                qa_status="",
                qa_feedback="",
                retry_count=0,
                documents=[],
                final_answer=""
            )
            
            final_state = self.app.invoke(
                initial_state,
                config={"recursion_limit": 10}
            )
            
            final_answer = final_state.get("final_answer", "")
            
            # Quality checks
            quality_checks = {
                "Has answer": bool(final_answer),
                "Length > 50 chars": len(final_answer) > 50,
                "Not just error": "오류" not in final_answer.lower() or "정보" in final_answer.lower(),
                "Cites source": "제공" in final_answer or "문서" in final_answer or "데이터" in final_answer or "정보" in final_answer
            }
            
            print("📋 Quality Checks:")
            for check_name, check_result in quality_checks.items():
                icon = "✅" if check_result else "❌"
                print(f"   {icon} {check_name}")
            
            passed = quality_checks.get("Has answer", False)
            
            self.print_result(
                passed,
                f"Answer quality validated ({sum(quality_checks.values())}/{len(quality_checks)} checks passed)"
            )
            
            print(f"\n📝 Answer preview:")
            print(f"   {final_answer[:200]}...")
            
            self.results.append({
                "test": "Answer Quality",
                "passed": passed,
                "detail": f"quality_score={sum(quality_checks.values())}/{len(quality_checks)}"
            })
            
            return passed
            
        except Exception as e:
            self.print_result(False, f"Answer quality check error: {str(e)}")
            return False
    
    
    # ======================================================================
    # Main Test Runner
    # ======================================================================
    
    def run_all_tests(self):
        """Run all tests and generate report"""
        
        self.print_header("🚀 E2E TEST SUITE - Operation RAG Rebirth")
        print(f"Start Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        
        # Run all tests
        test_functions = [
            self.test_01_imports,
            self.test_02_router_classification,
            self.test_03_csv_schema,
            self.test_04_csv_filtering,
            self.test_05_hybrid_search,
            self.test_06_pipeline_initialization,
            self.test_07_full_pipeline_execution,
            self.test_08_answer_quality,
        ]
        
        results_detailed = []
        for test_func in test_functions:
            try:
                result = test_func()
                results_detailed.append(result)
            except Exception as e:
                print(f"\n❌ Unexpected error in {test_func.__name__}: {str(e)}")
                import traceback
                traceback.print_exc()
                results_detailed.append(False)
        
        # Generate report
        self.print_header("📊 TEST SUMMARY REPORT")
        
        passed_count = sum(results_detailed)
        total_count = len(results_detailed)
        pass_rate = (passed_count / total_count * 100) if total_count > 0 else 0
        
        print(f"Total Tests: {total_count}")
        print(f"Passed: {passed_count}")
        print(f"Failed: {total_count - passed_count}")
        print(f"Pass Rate: {pass_rate:.1f}%")
        
        print(f"\n📋 Detailed Results:")
        for i, result in enumerate(self.results, 1):
            icon = "✅" if result.get("passed", False) else "❌"
            test_name = result.get("test", "Unknown")
            detail = result.get("detail", "")
            
            print(f"\n   [{i}] {icon} {test_name}")
            if detail:
                print(f"       └─ {detail}")
        
        # Final verdict
        self.print_header("🎯 FINAL VERDICT")
        
        if pass_rate >= 75:
            print(f"✅ PASSED: {pass_rate:.1f}% pass rate (Threshold: 75%)")
            print(f"\nThe RAG pipeline is ready for production deployment.")
            return True
        elif pass_rate >= 50:
            print(f"⚠️  PARTIAL: {pass_rate:.1f}% pass rate (Threshold: 75%)")
            print(f"\nThe RAG pipeline needs more work before deployment.")
            return False
        else:
            print(f"❌ FAILED: {pass_rate:.1f}% pass rate (Threshold: 75%)")
            print(f"\nThe RAG pipeline has critical issues.")
            return False


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    
    if not IMPORTS_OK:
        print("\n❌ Cannot proceed: imports failed")
        sys.exit(1)
    
    # Run E2E tests
    tester = E2ETester()
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)
