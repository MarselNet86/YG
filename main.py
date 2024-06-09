import logging
import random
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from fake_useragent import UserAgent
from web3 import Web3
from web3.middleware import geth_poa_middleware

from config import MOON_OR_DOOM_ABI, bets
from models import Network, Blast
from utils import read_json


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
logger = logging.getLogger(__name__)


class YoloGames:
    router_abi = read_json(MOON_OR_DOOM_ABI)
    router_address = Web3.to_checksum_address('0x693B37a9859Ce9465Fb2aAdeB03811a26A0c37C0')

    def __init__(self, private_key: str, network: Network):
        self.ua = UserAgent()
        self.private_key = private_key
        self.network = network
        self.w3 = Web3(Web3.HTTPProvider(endpoint_uri=self.network.rpc))
        self.address = Web3.to_checksum_address(self.w3.eth.account.from_key(private_key=private_key).address)

    @staticmethod
    def get_max_priority_fee_per_gas(w3: Web3, block: dict) -> int:
        block_number = block['number']
        latest_block_transaction_count = w3.eth.get_block_transaction_count(block_number)
        max_priority_fee_per_gas_lst = []
        for i in range(latest_block_transaction_count):
            try:
                transaction = w3.eth.get_transaction_by_block(block_number, i)
                if 'maxPriorityFeePerGas' in transaction:
                    max_priority_fee_per_gas_lst.append(transaction['maxPriorityFeePerGas'])
            except Exception:
                continue

        if not max_priority_fee_per_gas_lst:
            max_priority_fee_per_gas = w3.eth.max_priority_fee
        else:
            max_priority_fee_per_gas_lst.sort()
            max_priority_fee_per_gas = max_priority_fee_per_gas_lst[len(max_priority_fee_per_gas_lst) // 2]
        return max_priority_fee_per_gas

    def send_transaction(
            self,
            to,
            data=None,
            from_=None,
            increase_gas=1.,
            value=None,
            max_priority_fee_per_gas: Optional[int] = None,
            max_fee_per_gas: Optional[int] = None
    ):
        if not from_:
            from_ = self.address

        try:
            tx_params = {
                'chainId': self.w3.eth.chain_id,
                'nonce': self.w3.eth.get_transaction_count(self.address),
                'from': Web3.to_checksum_address(from_),
                'to': Web3.to_checksum_address(to),
            }
            if data:
                tx_params['data'] = data

            if self.network.eip1559_tx:
                w3 = Web3(provider=Web3.HTTPProvider(endpoint_uri=self.network.rpc))
                w3.middleware_onion.inject(geth_poa_middleware, layer=0)

                last_block = w3.eth.get_block('latest')
                if not max_priority_fee_per_gas:
                    max_priority_fee_per_gas = self.get_max_priority_fee_per_gas(w3=w3, block=last_block)
                if not max_fee_per_gas:
                    base_fee = int(last_block['baseFeePerGas'] * increase_gas)
                    max_fee_per_gas = base_fee + max_priority_fee_per_gas
                tx_params['maxPriorityFeePerGas'] = max_priority_fee_per_gas
                tx_params['maxFeePerGas'] = max_fee_per_gas
            else:
                tx_params['gasPrice'] = self.w3.eth.gas_price

            if value:
                tx_params['value'] = value

            tx_params['gas'] = int(self.w3.eth.estimate_gas(tx_params) * increase_gas)

        except Exception as err:
            logger.error(f'{self.address} | Transaction failed | {err}')
            return None

        sign = self.w3.eth.account.sign_transaction(tx_params, self.private_key)
        return self.w3.eth.send_raw_transaction(sign.rawTransaction)

    def moon_or_doom(self, amount: float = 0.01, epoch=None, enter_type=None):
        contract = self.w3.eth.contract(
            abi=YoloGames.router_abi,
            address=YoloGames.router_address
        )

        return self.send_transaction(
            to=YoloGames.router_address,
            data=contract.encodeABI(enter_type,
                                    args=(
                                        epoch,
                                    )),
            value=self.w3.to_wei(str(amount), 'ether')
        )

    def claim(self, amount: float = 0, epoch=None, ):
        contract = self.w3.eth.contract(
            abi=YoloGames.router_abi,
            address=YoloGames.router_address
        )
        return self.send_transaction(
            to=YoloGames.router_address,
            data=contract.encodeABI('claim',
                                    args=(
                                        [epoch],
                                    )),
            value=self.w3.to_wei(str(amount), 'ether')
        )

    def verif_tx(self, tx_hash) -> bool:
        try:
            data = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=200)
            if 'status' in data and data['status'] == 1:
                return True
            else:
                logger.error(f'{self.address} | transaction failed {data["transactionHash"].hex()}')
                return False
        except Exception as ex:
            logger.error(f'{self.address} | unexpected error in <verif_tx> function: {ex}')
            return False

    def generate_headers(self):
        headers = {
            'accept': '*/*',
            'accept-language': 'ru-RU,ru;q=0.9',
            'content-type': 'application/json',
            'origin': 'https://yologames.io',
            'priority': 'u=1, i',
            'referer': 'https://yologames.io/',
            'sec-ch-ua': '"Brave";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-site',
            'sec-gpc': '1',
            'user-agent': self.ua.chrome,
        }
        return headers

    def check_winner(self, epoch: int, player: str):
        url = "https://graphql.yologames.io/graphql"
        headers = self.generate_headers()
        payload = {
            "query": """
                query MoDRound($contract: MoDContract!, $id: Int, $player: Address) {
                    modRound(contract: $contract, id: $id) {
                        ...MoDRound
                    }
                }
                fragment MoDRound on MoDRound {
                    id
                    onChainId
                    result {
                        result
                        payoutRatio
                    }
                    entries(player: $player) {
                        moonPosition
                        amount
                        payoutAmount
                    }
                }
            """,
            "variables": {
                "contract": "MOON_OR_DOOM_ETHUSD_V1_BLAST",
                "id": epoch,
                "player": player
            }
        }
        try:
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                result_data = response.json()
                entries = result_data['data']['modRound']['result']['result']
                return entries
            else:
                return False
        except Exception as ex:
            logger.error(ex)

    def get_graph_info(self):
        url = "https://graphql.yologames.io/graphql"
        headers = self.generate_headers()
        payload = "{\"query\":\"\\n    query MoDRounds($filter: MoDFilterInput!, $player: Address, $pagination: PaginationInput) {\\n      modRounds(filter: $filter, pagination: $pagination) {\\n        ...MoDRound\\n      }\\n    }\\n    \\n  fragment MoDRound on MoDRound {\\n    id\\n    onChainId\\n    startedAt\\n    lockedAt\\n    closedAt\\n    lockPrice\\n    closePrice\\n    oracleCalled\\n\\n    totalAmount\\n    moonAmount\\n    moonPayoutRatio\\n    doomAmount\\n    doomPayoutRatio\\n    status\\n    result {\\n      ...MoDRoundResult\\n    }\\n\\n    setting {\\n      ...MoDRoundSetting\\n    }\\n    entries(player: $player) {\\n      ...MoDEntry\\n    }\\n  }\\n  \\n  fragment MoDRoundResult on MoDRoundResult {\\n    result\\n    payoutRatio\\n  }\\n\\n  \\n  fragment MoDRoundSetting on MoDRoundSetting {\\n    minimumEnterAmount\\n    roundIntervalSecs\\n  }\\n\\n  \\n  fragment MoDEntry on MoDEntry {\\n    moonPosition\\n    amount\\n    payoutAmount\\n  }\\n\\n\\n  \",\"variables\":{\"filter\":{\"contract\":\"MOON_OR_DOOM_ETHUSD_V1_BLAST\"},\"pagination\":{\"first\":1}}}"
        try:
            response = requests.post(url, headers=headers, data=payload)
            return response.json()
        except Exception as ex:
            logger.error(ex)

    @staticmethod
    def formatting_to_iso(date) -> datetime:
        return datetime.fromisoformat(date.replace('Z', '+00:00'))

    def date_counting(self):
        graph_info = self.get_graph_info()
        if graph_info:
            current_time = datetime.now(timezone.utc)

            for round_info in graph_info['data']['modRounds']:
                on_chain_id = round_info.get('onChainId')
                started_at = round_info.get('startedAt')
                closed_at = round_info.get('closedAt')

                moon = round_info.get('moonPayoutRatio')
                doom = round_info.get('doomPayoutRatio')

                started_at_dt = self.formatting_to_iso(started_at)
                closed_at_dt = self.formatting_to_iso(closed_at)

                try:
                    if current_time < started_at_dt:
                        logger.info(f"Игра еще не началась | onChainId {on_chain_id}")
                        continue

                    if current_time > started_at_dt + timedelta(seconds=12):
                        logger.info(
                            f"Игра не начинается: прошло больше 12 секунд с начала игры | Номер игры: {on_chain_id}")
                        sleep_time = (closed_at_dt - datetime.now(timezone.utc)).total_seconds()
                        if sleep_time > 0:
                            logger.info(f"Ожидание до завершения раунда: {sleep_time:.2f} секунд")
                            time.sleep(sleep_time + 15)
                        continue

                    if moon < 1.5 or doom < 1.5:
                        logger.info(
                            f"Игра не начинается: коэффициенты moon или doom меньше x1.5 |  {on_chain_id}")
                        continue

                    if abs(moon - doom) / ((moon + doom) / 2) > 0.05:
                        logger.info(
                            f"Игра не начинается: разница между doom и moon больше 5% | Номер игры: {on_chain_id}")
                        continue

                    logger.info(f"Поставили ставку | Номер игры: {on_chain_id} | Moon: {moon:.2f}x | Doom: {doom:.2f}x")
                    return on_chain_id, closed_at_dt

                except ZeroDivisionError:
                    logger.error("Ошибка деления на ноль при расчете коэффициентов.")
                    continue

        return None, None

    def get_balance(self):
        return self.w3.eth.get_balance(self.address)

    def transfer_funds(self, to_address, amount):
        tx_hash = self.send_transaction(
            to=to_address,
            value=self.w3.to_wei(amount, 'ether')
        )
        return tx_hash

    @classmethod
    def read_private_keys(cls, filename: str):
        with open(filename, 'r') as file:
            return [line.strip() for line in file.readlines()]

    @classmethod
    def main(cls):
        private_keys = cls.read_private_keys('private_keys.txt')
        if len(private_keys) != 2:
            logger.error("Файл private_keys.txt должен содержать ровно два приватных ключа.")
            return

        private_key_moon, private_key_doom = private_keys
        yolo_games_moon = YoloGames(private_key=private_key_moon, network=Blast)
        yolo_games_doom = YoloGames(private_key=private_key_doom, network=Blast)

        def transfer_funds_with_retry(from_game, to_game, amount):
            max_attempts = 3
            for attempt in range(max_attempts):
                random_sleep = random.randint(3, 10)
                try:
                    tx_hash = from_game.transfer_funds(to_game.address, amount)
                    logger.info(
                        f"Перевод {amount} ETH с кошелька {from_game.address} на кошелек {to_game.address} | tx_hash: {tx_hash.hex()}")
                    if from_game.verif_tx(tx_hash):
                        logger.info(f"Перевод подтвержден | tx_hash: {tx_hash.hex()}")
                        logger.info(f'Спим: {random_sleep} сек')
                        time.sleep(random_sleep)
                        return True
                    else:
                        logger.error(f"Перевод не подтвержден | tx_hash: {tx_hash.hex()}")
                except Exception as e:
                    logger.error(f"Ошибка при переводе средств: {e}")
                logger.info(f'Спим: {random_sleep} сек')
                time.sleep(random_sleep)
            return False

        def claim_with_retry(yolo_game, epoch):
            max_attempts = 3
            for attempt in range(max_attempts):
                random_sleep = random.randint(3, 10)
                try:
                    tx_hash = yolo_game.claim(epoch=epoch)
                    if tx_hash:
                        logger.info(
                            f"Транзакция claim отправлена с адреса {yolo_game.address}: {tx_hash.hex()}")
                        if yolo_game.verif_tx(tx_hash):
                            logger.info(
                                f"Транзакция claim подтверждена с адреса {yolo_game.address}: {tx_hash.hex()}")
                            return True
                        else:
                            logger.error(
                                f"Транзакция claim не подтверждена с адреса {yolo_game.address}: {tx_hash.hex()}")
                except Exception as e:
                    logger.error(f"Ошибка при отправке claim транзакции: {e}")
                logger.info(f'Спим: {random_sleep} сек')
                time.sleep(random_sleep)
            return False

        while True:
            # Случайный выбор суммы ставки
            bet_amount = random.choice(bets)

            # Проверка баланса кошельков перед каждым раундом
            moon_balance_wei = yolo_games_moon.get_balance()
            doom_balance_wei = yolo_games_doom.get_balance()

            moon_balance_ether = yolo_games_moon.w3.from_wei(moon_balance_wei, 'ether')
            doom_balance_ether = yolo_games_moon.w3.from_wei(doom_balance_wei, 'ether')

            if moon_balance_ether < bet_amount:
                if doom_balance_ether >= bet_amount:
                    transfer_amount = yolo_games_doom.w3.from_wei(round(doom_balance_wei / 2), 'ether')
                    if not transfer_funds_with_retry(yolo_games_doom, yolo_games_moon, transfer_amount):
                        logger.error("Недостаточно средств на обоих кошельках для начала игры.")
                        return
                else:
                    logger.error("Недостаточно средств на обоих кошельках для начала игры.")
                    return
            elif doom_balance_ether < bet_amount:
                if moon_balance_ether >= bet_amount:
                    transfer_amount = yolo_games_doom.w3.from_wei(round(moon_balance_wei / 2), 'ether')
                    if not transfer_funds_with_retry(yolo_games_moon, yolo_games_doom, transfer_amount):
                        logger.error("Недостаточно средств на обоих кошельках для начала игры.")
                        return
                else:
                    logger.error("Недостаточно средств на обоих кошельках для начала игры.")
                    return

            on_chain_id, closed_at_dt = yolo_games_moon.date_counting()
            if on_chain_id and closed_at_dt:
                # Случайное распределение ролей между кошельками
                wallets = [(yolo_games_moon, 'enterMoon'), (yolo_games_doom, 'enterDoom')]
                if random.choice([True, False]):
                    wallets = [(yolo_games_doom, 'enterMoon'), (yolo_games_moon, 'enterDoom')]

                for yolo_game, enter_type in wallets:
                    tx_hash = yolo_game.moon_or_doom(amount=bet_amount, epoch=on_chain_id, enter_type=enter_type)
                    if tx_hash:
                        logger.info(f"Ставка: {bet_amount} ETH | Транзакция {enter_type} отправлена с адреса {yolo_game.address}: {tx_hash.hex()}")
                        if yolo_game.verif_tx(tx_hash):
                            logger.info(
                                f"Ставка: {bet_amount} ETH | Транзакция {enter_type} подтверждена с адреса {yolo_game.address}: {tx_hash.hex()}")
                        else:
                            logger.error(
                                f"Ставка: {bet_amount} ETH | Транзакция {enter_type} не подтверждена с адреса {yolo_game.address}: {tx_hash.hex()}")

                # Ожидание завершения раунда
                sleep_time = (closed_at_dt - datetime.now(timezone.utc)).total_seconds() + random.randint(13, 18)
                if sleep_time > 0:
                    logger.info(f"Ожидание до завершения раунда: {sleep_time:.2f} секунд")
                    time.sleep(sleep_time)

                logger.info(f"Пробуем клеймить награду с {yolo_games_moon.address} | Номер игры: {on_chain_id}")
                if not claim_with_retry(yolo_games_moon, on_chain_id):
                    logger.error("Не удалось заклеймить после 3 попыток.")

                    logger.info(f"Пробуем клеймить награду с {yolo_games_doom.address} | Номер игры: {on_chain_id}")
                    if not claim_with_retry(yolo_games_doom, on_chain_id):
                        logger.error("Не удалось заклеймить после 3 попыток.")

            time.sleep(0.5)


if __name__ == "__main__":
    YoloGames.main()
