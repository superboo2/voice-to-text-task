import asyncio
from datetime import datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from fastapi import status
from httpx import AsyncClient, ASGITransport

import main


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def clear():  # clear fake db before each test
    main.users.clear()
    main.records.clear()
    main.user_semaphores.clear()
    main.current_user_id = 0


class TestUser:
    user_data = {"username": "Gandalf Grey", "password": "gandalfExampleSecret"}

    def test_register_successfully(self):
        response = client.post("/register", json=self.user_data)
        assert response.status_code == status.HTTP_201_CREATED

        register_user = next((user for user in main.users if user.id == 1), None)
        assert register_user.credits == 10

    def test_register_successfully_id_increment(self):
        response = client.post("/register", json=self.user_data)
        assert response.status_code == status.HTTP_201_CREATED

        response = client.post("/register", json={"username": "Radagast Brown", "password": "radagastExampleSecret"})
        assert response.status_code == status.HTTP_201_CREATED

        assert next((user for user in main.users if user.id == 1), None)
        assert next((user for user in main.users if user.id == 2), None)

    def test_register_unsuccessfully_username_already_exists(self):
        response = client.post("/register", json=self.user_data)
        assert response.status_code == status.HTTP_201_CREATED

        response = client.post("/register", json=self.user_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {"detail": "Username already exists"}

    def test_login_successfully(self):
        client.post("/register", json=self.user_data)

        response = client.post("/login", data=self.user_data)
        assert response.status_code == status.HTTP_200_OK

        result = response.json()
        assert "access_token" in result
        assert "refresh_token" in result

    def test_login_unsuccessfully_wrong_password(self):
        client.post("/register", json=self.user_data)

        self.user_data["password"] = "wrongPassword"
        response = client.post("/login", data=self.user_data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

        result = response.json()
        assert result["detail"] == "Invalid username or password"

    def test_user_get_profile_successfully(self):
        client.post("/register", json=self.user_data)
        response_login = client.post("/login", data=self.user_data)
        result_login = response_login.json()
        access_token = result_login["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        response_user = client.get("/user", headers=headers)
        assert response_user.status_code == status.HTTP_200_OK
        result_user = response_user.json()
        assert result_user == {"username": "Gandalf Grey", "credits": 10}

    def test_user_get_profile_unsuccessfully_unauthorized_user(self):
        response_user = client.get("/user")
        assert response_user.status_code == status.HTTP_401_UNAUTHORIZED
        assert response_user.json()["detail"] == "Not authenticated"


class TestRecord:
    user_data = {"username": "Gandalf Grey", "password": "gandalfExampleSecret"}
    short_text = "Hello World"  # 2 words/credits
    long_text = "Seven to the Dwarf-Lords, great miners and craftsmen of the mountain halls."  # 12 words/credits

    @classmethod
    @pytest.fixture(autouse=True)
    def setup_user(cls):
        client.post("/register", json=cls.user_data)
        response_login = client.post("/login", data=cls.user_data)
        result_login = response_login.json()
        access_token = result_login["access_token"]
        cls.headers = {"Authorization": f"Bearer {access_token}"}

    def test_records_create_record_successfully(self):
        user = next((user for user in main.users if user.id == 1), None)
        assert user.credits == 10  # user credits before

        response = client.post("/records", json={"text": self.short_text}, headers=self.headers)
        assert response.status_code == status.HTTP_200_OK
        assert response.headers["Content-Type"] == "audio/mpeg"
        assert response.headers["Content-Disposition"] == "attachment; filename=record.mp3"
        assert len(response.content) > 1000

        user = next((user for user in main.users if user.id == 1), None)
        assert user.credits == 8  # user credits after

    def test_records_create_record_unsuccessfully_user_has_low_credits(self):
        user = next((user for user in main.users if user.id == 1), None)
        assert user.credits == 10  # user credits before

        response = client.post("/records", json={"text": self.long_text}, headers=self.headers)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "You have not enough credits. Your credits: 10, the cost is 12 credits."

        user = next((user for user in main.users if user.id == 1), None)
        assert user.credits == 10  # user credits after

    def test_records_create_record_unsuccessfully_unauthorized_user(self):
        response = client.post("/records", json={"text": self.short_text})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_middleware_limit_concurrent_requests_successfully(self):
        async with AsyncClient(transport=ASGITransport(main.app), base_url="http://127.0.0.1:8005/") as client_async:
            finish_times = {}

            async def track_request(name, headers_data):
                response = await client_async.post("/concurrent-requests", json={"text": "a"}, headers=headers_data)
                finish_times[name] = datetime.now().replace(microsecond=0)
                return response

            task1 = track_request(name="Task1", headers_data=self.headers)
            task2 = track_request(name="Task2", headers_data=self.headers)
            task3 = track_request(name="Task3", headers_data=self.headers)
            task4 = track_request(name="Task4", headers_data=self.headers)
            await asyncio.gather(task1, task2, task3, task4)

            assert finish_times["Task1"] == finish_times["Task2"] == finish_times["Task3"]
            assert finish_times["Task4"] > finish_times["Task3"] + timedelta(seconds=2)

    @pytest.mark.asyncio
    async def test_middleware_limit_concurrent_requests_successfully_two_users(self):
        async with AsyncClient(transport=ASGITransport(main.app), base_url="http://127.0.0.1:8005/") as client_async:
            second_user_data = {"username": "Sam", "password": "samExampleSecret"}
            await client_async.post("/register", json=second_user_data)
            response_login = await client_async.post("/login", data=second_user_data)
            result_login = response_login.json()
            access_token = result_login["access_token"]
            headers_user_two = {"Authorization": f"Bearer {access_token}"}

            async def track_request(name, headers_data):
                response = await client_async.post("/concurrent-requests", json={"text": "a"}, headers=headers_data)
                finish_times[name] = datetime.now().replace(microsecond=0)
                return response

            finish_times = {}
            task1 = track_request(name="Task1", headers_data=self.headers)
            task2 = track_request(name="Task2", headers_data=headers_user_two)
            task3 = track_request(name="Task3", headers_data=self.headers)
            task4 = track_request(name="Task4", headers_data=self.headers)

            await asyncio.gather(task1, task2, task3, task4)
            assert finish_times["Task1"] == finish_times["Task2"] == finish_times["Task3"] == finish_times["Task4"]
