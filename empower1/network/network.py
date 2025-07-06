import threading
import time
from flask import Flask, request, jsonify
import requests

from empower1.blockchain.blockchain import Blockchain, USER_PUBLIC_KEYS, VALIDATOR_WALLETS
from empower1.blockchain.transaction import Transaction
from empower1.blockchain.block import Block
from empower1.network.node import Node # This path should be correct
from empower1.network.messages import MessageType # This path should be correct
from empower1.blockchain.wallet import Wallet

class Network:
    def __init__(self, blockchain: Blockchain, host: str, port: int, node_id: str = None, seed_nodes: set = None, node_wallet: Wallet = None):
        self.blockchain = blockchain
        self.node_wallet_for_operations = node_wallet

        if hasattr(self.blockchain, 'set_network_interface'):
            self.blockchain.set_network_interface(self)
        elif hasattr(self.blockchain, 'network_interface'):
             self.blockchain.network_interface = self

        self.self_node = Node(host=host, port=port, node_id=node_id or (node_wallet.address if node_wallet else f"{host}:{port}"))
        self.peers = set()
        self.seen_tx_ids_broadcast = set()
        self.seen_block_hashes_broadcast = set()
        self.syncing_in_progress = False
        self.app = Flask(__name__)
        self._configure_routes()
        self.seed_nodes = seed_nodes or set()
        if self.self_node.address in self.seed_nodes:
            self.seed_nodes.remove(self.self_node.address)

    def _configure_routes(self):
        @self.app.route('/ping', methods=['GET'])
        def ping(): return jsonify({"message": "pong", "node_id": self.self_node.node_id, "address": self.self_node.address}), 200
        @self.app.route(f"/{str(MessageType.GET_CHAIN)}", methods=['GET'])
        def get_chain_endpoint():
            try: chain_data_dicts = [block.to_dict() for block in self.blockchain.chain]
            except Exception as e: return jsonify({"error": "Failed to serialize chain data", "details": str(e)}), 500
            return jsonify({"chain": chain_data_dicts, "length": len(self.blockchain.chain)}), 200
        @self.app.route(f"/{str(MessageType.GET_PEERS)}", methods=['GET'])
        def get_peers_api(): return jsonify({"peers": [p.address for p in list(self.peers)], "node_id": self.self_node.node_id}), 200
        @self.app.route(f"/{str(MessageType.NEW_PEER_ANNOUNCE)}", methods=['POST'])
        def new_peer_announce_api():
            data=request.get_json(); P="address"; E="error"; M="message"
            if not data or P not in data: return jsonify({E:"Missing peer address"}),400
            pa=data[P]
            print(f"!!! DBG Node {self.self_node.port}: Received NEW_PEER_ANNOUNCE for {pa}", flush=True)
            if not isinstance(pa,str) or not pa.startswith("http://"): return jsonify({E:"Invalid peer address format"}),400
            if pa==self.self_node.address: return jsonify({M:"Cannot add self as peer"}),400
            try:
                pn=Node.from_address_string(pa)
                # Changed: connect_to_peer will handle adding and further peer requests.
                # This endpoint is just for being informed about a peer.
                if self.connect_to_peer(pa): # Use pa (string) for connect_to_peer
                    return jsonify({M:"Peer connection process initiated", "peer_address":pa}), 202 # Accepted for processing
                else:
                    return jsonify({M:"Peer is self or connection failed"}), 400
            except ValueError as e: return jsonify({E:f"Invalid peer address: {str(e)}"}),400
            except Exception as e: return jsonify({E:f"Failed to process peer: {str(e)}"}),500
        @self.app.route(f"/{str(MessageType.NEW_TRANSACTION)}", methods=['POST'])
        def new_transaction_api():
            d=request.get_json(); E="error"; M="message"
            if not d: return jsonify({E:"No data"}),400
            if self.handle_received_transaction(d): return jsonify({M:"Tx processed"}),200
            else: return jsonify({M:"Failed to process tx"}),400
        @self.app.route(f"/{str(MessageType.NEW_BLOCK)}", methods=['POST'])
        def new_block_api():
            d=request.get_json(); E="error"; M="message"
            if not d: return jsonify({E:"No data"}),400
            if self.handle_received_block(d): return jsonify({M:"Block processed"}),200
            else: return jsonify({M:"Failed to process block"}),400
        @self.app.route('/debug_stake_self', methods=['POST'])
        def debug_stake_self():
            if not self.node_wallet_for_operations:return jsonify({"error":"Node wallet not configured"}),500
            d=request.get_json(); E="error"; M="message"
            if not d or'amount'not in d:return jsonify({E:"Missing amount"}),400
            try:
                sa=float(d['amount']);
                if sa<=0:return jsonify({E:"Stake must be positive"}),400
                self.blockchain.register_validator_wallet(self.node_wallet_for_operations,sa)
                VALIDATOR_WALLETS[self.node_wallet_for_operations.address]=self.node_wallet_for_operations
                return jsonify({M:f"Node {self.self_node.node_id} staked {sa}"}),200
            except ValueError:return jsonify({E:"Invalid stake amount"}),400
            except Exception as e:return jsonify({E:f"Staking failed: {str(e)}"}),500
        @self.app.route('/debug_create_tx', methods=['POST'])
        def debug_create_tx():
            if not self.node_wallet_for_operations:return jsonify({"error":"Node wallet not configured"}),500
            d=request.get_json();E="error";M="message"
            if not d or'receiver_address'not in d or'amount'not in d:return jsonify({E:"Missing receiver or amount"}),400
            try:
                r=d['receiver_address'];amt=float(d['amount']);aid=d.get('asset_id',Blockchain.NATIVE_CURRENCY_SYMBOL)
                if amt<=0:return jsonify({E:"Amount must be positive"}),400
                tx=Transaction(self.node_wallet_for_operations.address,r,amt,aid)
                tx.sign(self.node_wallet_for_operations)
                if self.blockchain.add_transaction(tx,self.node_wallet_for_operations.get_public_key_hex()):
                    return jsonify({M:"Tx created and added", "tx_id":tx.transaction_id}),201
                else:return jsonify({M:"Failed to add tx (check node logs)"}),400
            except ValueError:return jsonify({E:"Invalid amount"}),400
            except Exception as e:return jsonify({E:f"Tx creation failed: {str(e)}"}),500
        @self.app.route('/debug_faucet', methods=['POST'])
        def debug_faucet_endpoint():
            d=request.get_json();E="error";M="message"
            if not d or'address'not in d or'amount'not in d:return jsonify({E:"Missing address/amount"}),400
            try:
                ta=d['address'];amt=float(d['amount'])
                if amt<=0:return jsonify({E:"Amount must be positive"}),400
                self.blockchain.balances[ta]=self.blockchain.balances.get(ta,0.0)+amt
                self.blockchain.total_supply_epc+=amt
                return jsonify({M:"Faucet funds added", "address":ta,"new_balance":self.blockchain.balances[ta]}),200
            except ValueError:return jsonify({E:"Invalid amount for faucet"}),400
            except Exception as e:return jsonify({E:f"Faucet failed: {str(e)}"}),500
        @self.app.route('/mine_block_debug', methods=['POST'])
        def mine_block_debug_endpoint():
            mb=self.blockchain.mine_pending_transactions()
            if mb:return jsonify({"message":"Block mined","block_hash":mb.hash,"index":mb.index}),200
            else:return jsonify({"message":"Mining failed/no txs (check logs)"}),500
        @self.app.route('/debug_get_user_public_keys', methods=['GET'])
        def debug_get_user_public_keys_endpoint(): return jsonify(USER_PUBLIC_KEYS),200
        @self.app.route('/debug_add_user_public_key', methods=['POST'])
        def debug_add_user_public_key_endpoint():
            d=request.get_json();E="error";M="message"
            if not d or'address'not in d or'public_key_hex'not in d:return jsonify({E:"Missing address/pk_hex"}),400
            print(f"!!! DBG Node {self.self_node.port}: Received /debug_add_user_public_key for {d['address']}", flush=True)
            USER_PUBLIC_KEYS[d['address']]=d['public_key_hex']
            print(f"!!! DBG Node {self.self_node.port}: USER_PUBLIC_KEYS dict ID: {id(USER_PUBLIC_KEYS)}, Now contains: {list(USER_PUBLIC_KEYS.keys())}", flush=True)
            return jsonify({M:f"PK for {d['address']} added/updated."}),200
        @self.app.route('/debug_connect_to_peer', methods=['POST'])
        def debug_connect_to_peer_endpoint():
            data = request.get_json()
            if not data or 'address' not in data: return jsonify({"error": "Missing peer address to connect to"}), 400
            peer_addr_to_connect = data['address']
            if self.connect_to_peer(peer_addr_to_connect): return jsonify({"message": f"Conn attempt to {peer_addr_to_connect} success"}), 200
            else: return jsonify({"message": f"Conn attempt to {peer_addr_to_connect} failed"}), 400

    def start_server(self, threaded=True):
        if threaded:
            st=threading.Thread(target=lambda:self.app.run(host=self.self_node.host,port=self.self_node.port,debug=False,use_reloader=False))
            st.daemon=True;st.start()
        else:self.app.run(host=self.self_node.host,port=self.self_node.port,debug=True)

    def _send_http_request(self, method:str,pa:str,ep:str,jd:dict=None,t=5) -> dict|None:
        try:
            u=f"{pa}{ep}";r=requests.request(method.upper(),u,json=jd,timeout=t) if method.upper()=='POST' else requests.get(u,timeout=t)
            r.raise_for_status();return r.json()
        except requests.exceptions.RequestException as e:print(f"DBG Net Req Fail: {method} {pa}{ep} -> {e}", flush=True);return None

    def _announce_self_to_peer(self, pn:Node):
        # print(f"!!! DBG Node {self.self_node.port}: Announcing self to {pn.address}", flush=True)
        self._send_http_request('POST',pn.address,f"/{str(MessageType.NEW_PEER_ANNOUNCE)}",jd={"address":self.self_node.address})

    def connect_to_peer(self, pa:str) -> bool:
        print(f"!!! DBG Node {self.self_node.port}: connect_to_peer called for {pa}", flush=True)
        if pa==self.self_node.address:return False
        pr=self._send_http_request('GET',pa,'/ping')
        if pr and pr.get("address")==pa:
            try:
                pn=Node.from_address_string(pa);wn=self.add_peer(pn) # add_peer also calls request_chain_from_peer if needed
                if wn:self._announce_self_to_peer(pn)
                return True
            except ValueError:pass
        return False

    def connect_to_seed_nodes(self): [self.connect_to_peer(sa) for sa in list(self.seed_nodes)]

    def add_peer(self, pn:Node) -> bool:
        print(f"!!! DBG Node {self.self_node.port}: Attempting to add peer {pn.address}", flush=True)
        if pn.address==self.self_node.address or pn in self.peers:
            print(f"!!! DBG Node {self.self_node.port}: Peer {pn.address} is self or already known.", flush=True)
            return False
        self.peers.add(pn)
        print(f"!!! DBG Node {self.self_node.port}: Added peer {pn.address}. Total: {len(self.peers)}. Requesting their peers.", flush=True)
        self.request_peers_from(pn)

        print(f"!!! DBG Node {self.self_node.port}: Checking sync condition after adding {pn.address}. My chain len: {len(self.blockchain.chain)}, Sync in progress: {self.syncing_in_progress}", flush=True)
        if len(self.blockchain.chain) <= 1 and not self.syncing_in_progress:
            print(f"!!! DBG Node {self.self_node.port}: Chain short after adding peer {pn.address}, calling request_chain_from_peer.", flush=True)
            self.request_chain_from_peer(pn)
        return True

    def request_peers_from(self, pn:Node):
        # print(f"!!! DBG Node {self.self_node.port}: Requesting peers from {pn.address}", flush=True)
        rd=self._send_http_request('GET',pn.address,f"/{str(MessageType.GET_PEERS)}")
        if rd and 'peers'in rd:
            # print(f"!!! DBG Node {self.self_node.port}: Received peers from {pn.address}: {rd['peers']}", flush=True)
            for npa in rd['peers']:
                if npa!=self.self_node.address and not any(p.address==npa for p in self.peers):
                    # print(f"!!! DBG Node {self.self_node.port}: Attempting to connect to newly discovered peer {npa} from {pn.address}", flush=True)
                    self.connect_to_peer(npa) # This will ping, add, announce self, and request_peers_from again

    def get_known_peers_addresses(self)->list[str]:return [p.address for p in list(self.peers)]
    def broadcast_transaction(self,t:Transaction):
        if t.transaction_id in self.seen_tx_ids_broadcast:return
        td=t.to_dict();self.seen_tx_ids_broadcast.add(t.transaction_id)
        for pn in list(self.peers):self._send_http_request('POST',pn.address,f"/{str(MessageType.NEW_TRANSACTION)}",jd=td)
    def broadcast_block(self,b:Block):
        if b.hash in self.seen_block_hashes_broadcast:return
        bd=b.to_dict();self.seen_block_hashes_broadcast.add(b.hash)
        for pn in list(self.peers):self._send_http_request('POST',pn.address,f"/{str(MessageType.NEW_BLOCK)}",jd=bd)

    def handle_received_transaction(self,td:dict)->bool:
        try:
            req=['sender_address','receiver_address','amount','signature_hex','transaction_id']
            if not all(f in td for f in req):return False
            tid=td['transaction_id']
            if any(t.transaction_id==tid for t in self.blockchain.pending_transactions)or \
               any(any(t.transaction_id==tid for t in b.transactions)for b in self.blockchain.chain):return True
            trx=Transaction.from_dict(td)
            if trx.transaction_id!=tid:return False
            spk=USER_PUBLIC_KEYS.get(trx.sender_address)
            if not spk:print(f"DBG HRT: PK not found for {trx.sender_address} in USER_PUBLIC_KEYS: {list(USER_PUBLIC_KEYS.keys())}", flush=True);return False
            orig_ni=self.blockchain.network_interface;self.blockchain.network_interface=None
            s=self.blockchain.add_transaction(trx,spk,received_from_network=True)
            self.blockchain.network_interface=orig_ni
            if s and trx.transaction_id not in self.seen_tx_ids_broadcast:self.broadcast_transaction(trx)
            return s
        except Exception as e:print(f"DBG HRT Exc: {e}", flush=True);return False

    def handle_received_block(self,bd:dict)->bool:
        try:
            rb=Block.from_dict(bd)
            if any(b.hash==rb.hash for b in self.blockchain.chain):return True
            cl=len(self.blockchain.chain);lb=self.blockchain.last_block
            is_direct_extension=(rb.index==cl and (lb and rb.previous_hash==lb.hash or cl==0 and rb.previous_hash=="0" and rb.index==0))
            vpk=USER_PUBLIC_KEYS.get(rb.validator_address)
            if not vpk:print(f"DBG HRB: Val PK {rb.validator_address} not found. Known: {list(USER_PUBLIC_KEYS.keys())}", flush=True);return False
            # Block hash is calculated on instantiation. Here we verify if the received hash matches a recalculation.
            if rb.hash!=rb.calculate_hash()or not rb.verify_block_signature(vpk):print(f"DBG HRB: Block sig/hash fail for block {rb.index} from {rb.validator_address}. Stored: {rb.hash}, Recalc: {rb.calculate_hash()}", flush=True);return False
            for tx in rb.transactions:
                tspk=USER_PUBLIC_KEYS.get(tx.sender_address)
                if not tspk:print(f"DBG HRB: Tx Sender PK {tx.sender_address} not found. Known: {list(USER_PUBLIC_KEYS.keys())}", flush=True); return False
                if not tx.verify_signature(tspk):print(f"DBG HRB: Tx sig fail {tx.transaction_id}", flush=True);return False
            if is_direct_extension:
                tb=self.blockchain.balances.copy();vbt=True
                for tx in rb.transactions:
                    if tx.asset_id==Blockchain.NATIVE_CURRENCY_SYMBOL:
                        sb=tb.get(tx.sender_address,0.0)
                        if sb<tx.amount:vbt=False;break
                        tb[tx.sender_address]=sb-tx.amount;tb[tx.receiver_address]=tb.get(tx.receiver_address,0.0)+tx.amount
                if not vbt:print(f"DBG HRB: Balance fail on temp check for block {rb.index}", flush=True);return False
                orig_ni=self.blockchain.network_interface;self.blockchain.network_interface=None
                for tx in rb.transactions:
                    if not self.blockchain._process_transaction_for_state_changes(tx):
                        print(f"DBG HRB: _process_tx_for_state_changes failed for tx {tx.transaction_id} in block {rb.index}", flush=True);
                        self.blockchain.network_interface=orig_ni; return False
                self.blockchain.chain.append(rb);self.blockchain.network_interface=orig_ni
                self.blockchain.pending_transactions=[ptx for ptx in self.blockchain.pending_transactions if ptx.transaction_id not in {t.transaction_id for t in rb.transactions}]
                if rb.hash not in self.seen_block_hashes_broadcast:self.broadcast_block(rb)
                return True
            elif rb.index>=cl and not self.syncing_in_progress and self.peers:
                print(f"DBG HRB: Received block {rb.index} from {rb.validator_address} indicates fork or this node is behind. Requesting chain from a peer.", flush=True)
                self.request_chain_from_peer(list(self.peers)[0]);return False
            return False
        except Exception as e:print(f"ERR handle_recv_block: {e}", flush=True);return False

    def request_chain_from_peer(self,pn:Node):
        print(f"!!! DBG Node {self.self_node.port}: ENTERING request_chain_from_peer for peer {pn.address}", flush=True)
        if self.syncing_in_progress: print(f"!!! DBG Node {self.self_node.port}: Sync already in progress, skipping for {pn.address}.", flush=True); return
        self.syncing_in_progress=True
        rd=self._send_http_request('GET',pn.address,f"/{str(MessageType.GET_CHAIN)}")
        if rd and'chain'in rd and'length'in rd:
            self.handle_chain_response(rd['chain'],pn)
        else: print(f"!!! DBG Node {self.self_node.port}: Failed to get chain from {pn.address} or invalid response: {rd}", flush=True)
        self.syncing_in_progress=False

    def handle_chain_response(self,rcd:list[dict],fpn:Node):
        print(f"!!! DBG HCR Node {self.self_node.port}: ENTERING handle_chain_response from peer {fpn.address}. Chain length received: {len(rcd) if rcd else 'None'}", flush=True)
        print(f"!!! DBG HCR Node {self.self_node.port}: My current chain length: {len(self.blockchain.chain)}. My USER_PUBLIC_KEYS dict ID: {id(USER_PUBLIC_KEYS)}, Known keys for: {list(USER_PUBLIC_KEYS.keys())}", flush=True)
        if not rcd: print(f"!!! DBG HCR Node {self.self_node.port}: Received empty chain data from {fpn.address}.", flush=True); return

        is_our_chain_just_genesis = len(self.blockchain.chain) == 1

        if not is_our_chain_just_genesis and len(rcd) <= len(self.blockchain.chain):
            print(f"!!! DBG HCR Node {self.self_node.port}: Received chain not longer or not new node. Ours:{len(self.blockchain.chain)} Theirs:{len(rcd)}", flush=True)
            return

        pc=[];
        try:
            for bd in rcd:pc.append(Block.from_dict(bd))
        except Exception as e:print(f"ERR deserializing rcvd chain: {e}", flush=True);return
        if not pc:print(f"!!! DBG HCR Node {self.self_node.port}: Prospective chain empty after deserialization.", flush=True);return

        valid_pc=True
        # If our chain is established (more than 1 block), prospective chain's genesis MUST match ours.
        if not is_our_chain_just_genesis and pc[0].hash!=self.blockchain.chain[0].hash:
            print(f"!!! DBG HCR Node {self.self_node.port}: Genesis mismatch. Ours:{self.blockchain.chain[0].hash[:7]} Theirs:{pc[0].hash[:7]}. Local chain > 1 block. Rejecting.", flush=True)
            valid_pc=False

        temp_bals={};
        if valid_pc:
            pgv_addr = pc[0].validator_address
            temp_bals[pgv_addr] = self.blockchain.total_supply_epc
            if is_our_chain_just_genesis and pc[0].hash != self.blockchain.chain[0].hash:
                print(f"!!! DBG HCR Node {self.self_node.port}: New node adopting new genesis {pc[0].hash[:7]} from validator {pgv_addr}.", flush=True)

        if valid_pc:
            temp_validated_pc = []
            for i in range(len(pc)):
                cb=pc[i]
                print(f"!!! DBG HCR Node {self.self_node.port}: Validating prospective block {i}, Val: {cb.validator_address}, Hash: {cb.hash[:7]}", flush=True)
                # cb.hash is what was received. cb.calculate_hash() is based on its current (deserialized) content.
                if cb.hash!=cb.calculate_hash():print(f"!!! DBG HCR Node {self.node.port}: Hash mismatch B{i}. Stored: {cb.hash}, Recalc: {cb.calculate_hash()}", flush=True);valid_pc=False;break
                vpk=USER_PUBLIC_KEYS.get(cb.validator_address)
                if i==0:
                    if cb.index!=0 or cb.previous_hash!="0":print(f"!!! DBG HCR Node {self.self_node.port}: Invalid G B{i} idx/prevH", flush=True);valid_pc=False;break
                    if not vpk: print(f"!!! DBG HCR Node {self.self_node.port}: Missing PK for G validator {cb.validator_address}. My Keys: {list(USER_PUBLIC_KEYS.keys())}", flush=True);valid_pc=False;break
                    if not cb.verify_block_signature(vpk):print(f"!!! DBG HCR Node {self.self_node.port}: Invalid G B{i} sig for {cb.validator_address}", flush=True);valid_pc=False;break
                else:
                    pb=temp_validated_pc[i-1]
                    if cb.previous_hash!=pb.hash or cb.index!=len(temp_validated_pc):print(f"!!! DBG HCR Node {self.self_node.port}: Link/Idx mismatch B{i}", flush=True);valid_pc=False;break
                    if not vpk: print(f"!!! DBG HCR Node {self.self_node.port}: Missing PK for B{i} validator {cb.validator_address}. My Keys: {list(USER_PUBLIC_KEYS.keys())}", flush=True); valid_pc=False; break
                    if not cb.verify_block_signature(vpk):print(f"!!! DBG HCR Node {self.self_node.port}: Invalid B{i} sig for {cb.validator_address}", flush=True);valid_pc=False;break
                for tx_idx, tx in enumerate(cb.transactions):
                    # print(f"!!! DBG HCR Node {self.self_node.port}: Validating B{i}/Tx{tx_idx}, Sender: {tx.sender_address}", flush=True)
                    tspk=USER_PUBLIC_KEYS.get(tx.sender_address)
                    if not tspk: print(f"!!! DBG HCR Node {self.self_node.port}: Missing PK for Tx sender {tx.sender_address} in B{i}. My Keys: {list(USER_PUBLIC_KEYS.keys())}", flush=True); valid_pc=False; break
                    if not tx.verify_signature(tspk):print(f"!!! DBG HCR Node {self.self_node.port}: Invalid Tx {tx.transaction_id[:7]} in B{i}", flush=True);valid_pc=False;break
                    if tx.asset_id==Blockchain.NATIVE_CURRENCY_SYMBOL:
                        sb=temp_bals.get(tx.sender_address,0.0)
                        if sb<tx.amount:print(f"!!! DBG HCR Node {self.self_node.port}: Insuff funds Tx {tx.transaction_id[:7]} in B{i} (Bal:{sb} Amt:{tx.amount})", flush=True);valid_pc=False;break
                        temp_bals[tx.sender_address]=sb-tx.amount;temp_bals[tx.receiver_address]=temp_bals.get(tx.receiver_address,0.0)+tx.amount
                if not valid_pc:break
                temp_validated_pc.append(cb)

        if valid_pc and len(pc) > len(self.blockchain.chain):
            print(f"[{self.self_node.node_id}] Received valid longer chain from {fpn.address} (len {len(pc)}). Updating local chain (len {len(self.blockchain.chain)}).", flush=True)
            self.blockchain.chain=pc;self.blockchain.balances=temp_bals;self.blockchain.pending_transactions=[]
            self.seen_block_hashes_broadcast.clear();self.seen_tx_ids_broadcast.clear()
            for b_in_chain in self.blockchain.chain:
                self.seen_block_hashes_broadcast.add(b_in_chain.hash)
                for txb_in_chain in b_in_chain.transactions:self.seen_tx_ids_broadcast.add(txb_in_chain.transaction_id)
        elif not valid_pc: print(f"[{self.self_node.node_id}] Received chain from {fpn.address} was invalid during HCR validation.", flush=True)

if __name__ == '__main__':
    class DemoBlockchain:
        def __init__(self):
            self.NATIVE_CURRENCY_SYMBOL = "EPC";self.total_supply_epc = 1_000_000.0
            gv=Wallet();USER_PUBLIC_KEYS[gv.address]=gv.get_public_key_hex();VALIDATOR_WALLETS[gv.address]=gv
            self.chain=[];self.balances={};gb=Block(0,[],time.time(),"0",gv.address)
            if gb:gb.sign_block(gv);self.chain.append(gb);self.balances[gv.address]=self.total_supply_epc
            self.pending_transactions=[];self.network_interface=None
            self.validator_manager = ValidatorManager()
        def add_transaction(self,t,spk,received_from_network=False):
            if t.verify_signature(spk):
                sbal=self.balances.get(t.sender_address,0.0)
                pout=sum(ptx.amount for ptx in self.pending_transactions if ptx.sender_address==t.sender_address and ptx.asset_id==self.NATIVE_CURRENCY_SYMBOL)
                if t.asset_id==self.NATIVE_CURRENCY_SYMBOL and sbal-pout<t.amount: return False
                if not any(tx.transaction_id==t.transaction_id for tx in self.pending_transactions):self.pending_transactions.append(t)
                if self.network_interface and not received_from_network:self.network_interface.broadcast_transaction(t)
                return True
            return False
        @property
        def last_block(self):return self.chain[-1] if self.chain else None
        def _process_transaction_for_state_changes(self,t:Transaction)->bool:
            if t.asset_id==self.NATIVE_CURRENCY_SYMBOL:
                sb=self.balances.get(t.sender_address,0.0)
                if sb<t.amount:return False
                self.balances[t.sender_address]=sb-tx.amount;self.balances[t.receiver_address]=self.balances.get(t.receiver_address,0.0)+tx.amount
            return True
        def mine_pending_transactions(self):
            if not self.pending_transactions: return None
            miner_wallet = self.network_interface.node_wallet_for_operations if self.network_interface and self.network_interface.node_wallet_for_operations else Wallet()
            if miner_wallet.address not in VALIDATOR_WALLETS:
                 VALIDATOR_WALLETS[miner_wallet.address]=miner_wallet;USER_PUBLIC_KEYS[miner_wallet.address]=miner_wallet.get_public_key_hex()
            validator_obj = self.validator_manager.get_validator(miner_wallet.address)
            if not validator_obj or not validator_obj.is_active:
                selected_val_obj = self.validator_manager.select_next_validator()
                if not selected_val_obj: return None
                miner_wallet = VALIDATOR_WALLETS.get(selected_val_obj.address)
                if not miner_wallet: return None
            b=Block(len(self.chain),list(self.pending_transactions),time.time(),self.last_block.hash,miner_wallet.address)
            b.sign_block(miner_wallet);[self._process_transaction_for_state_changes(tx)for tx in b.transactions];self.chain.append(b)
            self.pending_transactions=[];
            if self.network_interface:self.network_interface.broadcast_block(b)
            return b
        def register_validator_wallet(self, val_wallet: Wallet, stake: float):
            self.validator_manager.add_or_update_validator_stake(val_wallet.address, val_wallet.get_public_key_hex(), stake)

    demo_bc=DemoBlockchain();host=sys.argv[1]if len(sys.argv)>1 and not sys.argv[1].startswith("http")else "127.0.0.1"
    pcidx=2 if(len(sys.argv)>1 and not sys.argv[1].startswith("http"))else 1
    try:port=int(sys.argv[pcidx])if len(sys.argv)>pcidx and not sys.argv[pcidx].startswith("http")else 5000
    except(ValueError,IndexError):port=5000
    ssidx=pcidx+1 if(len(sys.argv)>pcidx and not sys.argv[pcidx].startswith("http"))else pcidx
    s_nodes=set(sys.argv[ssidx:])if len(sys.argv)>ssidx else set()
    v_seeds={sn for sn in s_nodes if sn.startswith("http://")and":"in sn.split("http://")[1]}
    node_mw=Wallet();USER_PUBLIC_KEYS[node_mw.address]=node_mw.get_public_key_hex()
    nm=Network(blockchain=demo_bc,host=host,port=port,seed_nodes=v_seeds,node_wallet=node_mw)
    demo_bc.network_interface=nm;nm.start_server(threaded=True);time.sleep(0.5)
    if v_seeds:nm.connect_to_seed_nodes()
    elif len(demo_bc.chain)<=1 and not v_seeds and sys.stdin.isatty():print(f"[{nm.self_node.node_id}] No seeds. Started with genesis.")
    if sys.stdin.isatty():print(f"\nNode {nm.self_node.node_id} running. API: {nm.self_node.address}\nPeers: {nm.get_known_peers_addresses()}")
    try:
        while True:time.sleep(15)
    except KeyboardInterrupt:print(f"\nNode {nm.self_node.node_id} shutting down.")
