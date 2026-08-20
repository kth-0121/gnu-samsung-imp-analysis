"""
Streamlit Community Cloud가 기본으로 찾는 진입점 파일.
실제 앱 로직은 ui/app.py에 있으며, 여기서는 그 main()을 호출하기만 한다.
"""

from ui.app import main

if __name__ == "__main__":
    main()
