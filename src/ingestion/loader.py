"""
CSV/Excel 파일 로드.
실제 데이터 컬럼 구조를 가정하지 않는다 - 여기서는 오직 '파일을 DataFrame으로
읽는다'는 책임만 가진다. 컬럼 해석은 schema_inference 모듈이 담당한다.
"""

from __future__ import annotations

import io
import pandas as pd


class DataLoadError(Exception):
    """사용자에게 그대로 보여줄 수 있는 친절한 에러 메시지를 담는다."""


def load_data(file, filename: str | None = None) -> pd.DataFrame:
    """
    file: 파일 경로(str) 또는 파일류 객체(Streamlit UploadedFile 등)
    filename: 파일류 객체를 넘길 때 확장자 판별용 원본 파일명
    """
    name = filename or getattr(file, "name", None) or (file if isinstance(file, str) else "")
    name = str(name).lower()

    try:
        if name.endswith(".csv"):
            df = pd.read_csv(file)
        elif name.endswith(".xlsx") or name.endswith(".xls"):
            df = pd.read_excel(file)
        else:
            # 확장자를 알 수 없으면 CSV로 우선 시도
            try:
                df = pd.read_csv(file)
            except Exception:
                if hasattr(file, "seek"):
                    file.seek(0)
                df = pd.read_excel(file)
    except pd.errors.EmptyDataError:
        raise DataLoadError("업로드한 파일에 데이터가 없습니다. 파일 내용을 확인해 주세요.")
    except pd.errors.ParserError as e:
        raise DataLoadError(f"파일 형식을 해석할 수 없습니다 (CSV 구조 오류 가능): {e}")
    except Exception as e:
        raise DataLoadError(f"파일을 읽는 중 오류가 발생했습니다: {e}")

    if df.empty:
        raise DataLoadError("업로드한 파일에 행(row)이 없습니다.")
    if df.shape[1] == 0:
        raise DataLoadError("업로드한 파일에서 컬럼을 인식하지 못했습니다.")

    # 컬럼명 앞뒤 공백 제거 (원본 이름은 보존, 공백만 제거)
    df.columns = [str(c).strip() for c in df.columns]

    return df
